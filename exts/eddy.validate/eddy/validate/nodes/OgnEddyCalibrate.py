"""Eddy Calibrate: PhysX compliant-contact parameters from the truth (see OgnEddyCalibrate.ogn)."""


class OgnEddyCalibrate:
    @staticmethod
    def compute(db) -> bool:
        from eddy.validate.node_runtime import compute

        return compute("calibrate", db)
