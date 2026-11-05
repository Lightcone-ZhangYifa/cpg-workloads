"""Versioned ASV fixture: outputs checked in setup, timing excludes setup."""


class Sum:
    params = [32, 1024]
    param_names = ["count"]
    version = "cpg035-sum-v1"
    rounds = 2
    repeat = 3
    number = 256

    def setup(self, count):
        self.data = tuple(range(count))
        if sum(self.data) != count * (count - 1) // 2:
            raise RuntimeError("sum fixture preflight failed")

    def time_sum(self, count):
        return sum(self.data)

    def track_checksum(self, count):
        return sum(self.data)
