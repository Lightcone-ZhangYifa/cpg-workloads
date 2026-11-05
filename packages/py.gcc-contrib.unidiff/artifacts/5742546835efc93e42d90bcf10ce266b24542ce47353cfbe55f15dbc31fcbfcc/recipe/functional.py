from unidiff import PatchSet
patch='--- a/file.txt\n+++ b/file.txt\n@@ -1 +1 @@\n-before\n+after\n'
p=PatchSet(patch.splitlines(keepends=True))
assert len(p)==1 and len(p[0])==1
hunk=p[0][0]
assert hunk.removed==1 and hunk.added==1
assert hunk[0].is_removed and hunk[1].is_added
print('CPG_FUNCTIONAL_OK:unidiff:real-hunk-parse')
