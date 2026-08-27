from .models import Lead


class Dedupe:
    def __init__(self, db):
        self.db = db

    def accept(self, lead: Lead) -> bool:
        payload = lead.to_dict()

        return self.db.insert_if_new(payload)
