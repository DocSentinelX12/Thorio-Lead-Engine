from . import gmail_imap_inbound as inbound


def test_message_id_normalization():
    assert inbound._normalize_message_id('<abc123@thorio.co>') == 'abc123@thorio.co'


def test_message_id_extraction():
    assert inbound._message_ids('refs <abc123@thorio.co> <reply@example.com>') == {'abc123@thorio.co', 'reply@example.com'}
