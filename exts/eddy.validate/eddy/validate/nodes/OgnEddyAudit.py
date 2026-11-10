"""Eddy Audit: a peak contact force graded against the finite-element truth (see OgnEddyAudit.ogn)."""


class OgnEddyAudit:
    @staticmethod
    def compute(db) -> bool:
        from eddy.validate.node_runtime import compute

        return compute("audit", db)
