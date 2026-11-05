from typing_extensions import TypedDict,Annotated,Required,NotRequired,get_type_hints
class CPGTyped(TypedDict):
    value:Required[int]
    label:NotRequired[str]
assert CPGTyped.__required_keys__=={'value'}
assert CPGTyped.__optional_keys__=={'label'}
assert Annotated[int,'cpg'].__metadata__==('cpg',)
print('CPG_FUNCTIONAL_OK:typing-extensions:typed-dict-runtime')
