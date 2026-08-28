from typing import Any, Dict


class LeadEngineHealth:
    """
    Health reporting for the lead engine.

    Health checks are intentionally defensive. A failure while
    checking the database must produce an unhealthy response
    rather than crashing the health caller.
    """

    def __init__(self, db):
        self.db = db

    def check(self) -> Dict[str, Any]:
        try:
            stats = self.db.stats()

            return {
                "healthy": True,
                "database": {
                    "healthy": True,
                    "lead_count": stats[0],
                },
            }

        except Exception:
            return {
                "healthy": False,
                "database": {
                    "healthy": False,
                    "lead_count": 0,
                },
            }


def health(db) -> Dict[str, Any]:
    """
    Return the current health status of the lead engine.
    """
    return LeadEngineHealth(db).check()


if __name__ == "__main__":
    print(
        "Lead engine health module loaded."
    )
