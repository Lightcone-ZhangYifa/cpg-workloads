# target must remain in this comment, including its spacing.
TEXT = "target"  # literal spelling is data


def target( value ):  # keep this comment
    return value * value + 3


def outer(value):
    # A closure resolves the module function, so its reference must change.
    def closure():
        return target(value)
    return closure()


def shadow(target):
    return target(5)


class Box:
    def target(self, value):
        return value - 2


target_suffix = 17
alias = target
if __name__ == "__main__":
    import json
    print(json.dumps([target(i) + outer(i) + alias(i) for i in range(-8, 9)]))
    print(shadow(lambda x: x + 10), Box().target(5), TEXT, target_suffix)
