#define _GNU_SOURCE
#include <arpa/inet.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <netdb.h>
#include <pthread.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

static int (*real_connect_fn)(int, const struct sockaddr *, socklen_t);
static pthread_once_t init_once = PTHREAD_ONCE_INIT;
static __thread int in_proxy;

static void init_real(void) {
    real_connect_fn = (int (*)(int, const struct sockaddr *, socklen_t))
        dlsym(RTLD_NEXT, "connect");
}

static int env_true(const char *name) {
    const char *v = getenv(name);
    return v && (!strcmp(v, "1") || !strcasecmp(v, "true") || !strcasecmp(v, "yes"));
}

static int is_private_v4(uint32_t host_order) {
    return ((host_order >> 24) == 10) ||
           ((host_order >> 20) == 0xAC1) ||
           ((host_order >> 16) == 0xC0A8);
}

static int connect_peer(int fd, const struct sockaddr_in *original) {
    const char *peer_host = getenv("THORIO_PEER_TUNNEL_HOST");
    const char *peer_port = getenv("THORIO_PEER_TUNNEL_PORT");
    const char *relay_token = getenv("THORIO_PEER_RELAY_TOKEN");
    if (!peer_host || !peer_port || !relay_token || !*peer_host || !*peer_port || !*relay_token) {
        fprintf(stderr, "THORIO_CONNECT_PROXY_MISSING_RELAY_CONFIG\\n");
        fflush(stderr);
        errno = ENETUNREACH;
        return -1;
    }

    struct addrinfo hints;
    memset(&hints, 0, sizeof(hints));
    hints.ai_family = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    struct addrinfo *result = NULL;
    int gai_rc = getaddrinfo(peer_host, peer_port, &hints, &result);
    if (gai_rc != 0 || !result) {
        fprintf(stderr, "THORIO_CONNECT_PROXY_DNS_FAIL host=%s port=%s rc=%d\\n", peer_host, peer_port, gai_rc);
        fflush(stderr);
        errno = EHOSTUNREACH;
        return -1;
    }

    int flags = fcntl(fd, F_GETFL, 0);
    int was_nonblocking = flags >= 0 && (flags & O_NONBLOCK);
    if (was_nonblocking) fcntl(fd, F_SETFL, flags & ~O_NONBLOCK);

    char original_ip[INET_ADDRSTRLEN] = {0};
    inet_ntop(AF_INET, &original->sin_addr, original_ip, sizeof(original_ip));
    fprintf(stderr, "THORIO_CONNECT_PROXY_ATTEMPT fd=%d destination=%s:%u tunnel=%s:%s nonblocking=%d\\n",
            fd, original_ip, (unsigned)ntohs(original->sin_port), peer_host, peer_port, was_nonblocking);
    fflush(stderr);
    int rc = real_connect_fn(fd, result->ai_addr, (socklen_t)result->ai_addrlen);
    if (rc == 0) {
        unsigned char header[45];
        memset(header, 0, sizeof(header));
        memcpy(header, "THORIO1", 7);
        strncpy((char *)header + 7, relay_token, 32);
        memcpy(header + 39, &original->sin_addr.s_addr, 4);
        memcpy(header + 43, &original->sin_port, 2);
        size_t sent = 0;
        while (sent < sizeof(header)) {
            ssize_t n = send(fd, header + sent, sizeof(header) - sent, MSG_NOSIGNAL);
            if (n <= 0) {
                int saved = errno;
                freeaddrinfo(result);
                if (was_nonblocking) fcntl(fd, F_SETFL, flags);
                errno = saved;
                return -1;
            }
            sent += (size_t)n;
        }
        // A tunnel connect is insufficient: wait for the relay to confirm that
        // the actual peer destination socket accepted this connection.
        struct pollfd ack_poll;
        ack_poll.fd = fd;
        ack_poll.events = POLLIN;
        ack_poll.revents = 0;
        int poll_rc = poll(&ack_poll, 1, 15000);
        if (poll_rc <= 0) {
            int saved = poll_rc == 0 ? ETIMEDOUT : errno;
            fprintf(stderr, "THORIO_CONNECT_PROXY_ACK_TIMEOUT fd=%d destination=%s:%u tunnel=%s:%s\\n",
                    fd, original_ip, (unsigned)ntohs(original->sin_port), peer_host, peer_port);
            fflush(stderr);
            freeaddrinfo(result);
            if (was_nonblocking) fcntl(fd, F_SETFL, flags);
            errno = saved;
            return -1;
        }
        unsigned char acknowledgement = 0xff;
        ssize_t ack_size = recv(fd, &acknowledgement, 1, 0);
        if (ack_size != 1 || acknowledgement != 0) {
            int saved = ack_size == 1 && acknowledgement == 1 ? ECONNREFUSED : ECONNRESET;
            fprintf(stderr, "THORIO_CONNECT_PROXY_UPSTREAM_REJECTED fd=%d destination=%s:%u tunnel=%s:%s ack_size=%zd ack=%u errno=%d\\n",
                    fd, original_ip, (unsigned)ntohs(original->sin_port), peer_host, peer_port,
                    ack_size, (unsigned)acknowledgement, saved);
            fflush(stderr);
            freeaddrinfo(result);
            if (was_nonblocking) fcntl(fd, F_SETFL, flags);
            errno = saved;
            return -1;
        }
        fprintf(stderr, "THORIO_CONNECT_PROXY_CONNECTED fd=%d destination=%s:%u tunnel=%s:%s\\n",
                fd, original_ip, (unsigned)ntohs(original->sin_port), peer_host, peer_port);
        fflush(stderr);
        freeaddrinfo(result);
        if (was_nonblocking) fcntl(fd, F_SETFL, flags);
        return 0;
    }

    int saved = errno;
    fprintf(stderr, "THORIO_CONNECT_PROXY_CONNECT_FAIL fd=%d destination=%s:%u tunnel=%s:%s errno=%d\\n",
            fd, original_ip, (unsigned)ntohs(original->sin_port), peer_host, peer_port, saved);
    fflush(stderr);
    freeaddrinfo(result);
    if (was_nonblocking) fcntl(fd, F_SETFL, flags);
    errno = saved;
    return -1;
}

int connect(int fd, const struct sockaddr *addr, socklen_t addrlen) {
    pthread_once(&init_once, init_real);
    if (!real_connect_fn || in_proxy || env_true("THORIO_CONNECT_PROXY_DISABLE") ||
        !addr || addr->sa_family != AF_INET || addrlen < sizeof(struct sockaddr_in)) {
        return real_connect_fn(fd, addr, addrlen);
    }

    const struct sockaddr_in *in = (const struct sockaddr_in *)addr;
    uint32_t host_ip = ntohl(in->sin_addr.s_addr);
    if (!is_private_v4(host_ip)) {
        return real_connect_fn(fd, addr, addrlen);
    }

    in_proxy = 1;
    int rc = connect_peer(fd, in);
    in_proxy = 0;
    return rc;
}
