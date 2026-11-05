from interface_meta import InterfaceMeta,override
class Base(metaclass=InterfaceMeta):
    def answer(self,n):
        return n
class Derived(Base):
    @override
    def answer(self,n):
        return n * 6
assert Derived().answer(7)==42
print('CPG_FUNCTIONAL_OK:interface-meta:explicit-override')
