from typing_extensions import TypedDict,Required,NotRequired,Annotated
class CPGTyped(TypedDict):
    count:Required[int]
    hint:NotRequired[str]
assert CPGTyped.__required_keys__=={'count'}
assert CPGTyped.__optional_keys__=={'hint'}
assert Annotated[str,'gcc'].__metadata__==('gcc',)
print('CPG_FUNCTIONAL_OK:typing-extensions:gcc-role')
