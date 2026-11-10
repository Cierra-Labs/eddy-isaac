"""Eddy Truth Solve: a box body's stress under a face load, keyed (see OgnEddyTruthSolve.ogn)."""


class OgnEddyTruthSolve:
    @staticmethod
    def compute(db) -> bool:
        from eddy.validate.node_runtime import compute

        return compute("truth", db)
