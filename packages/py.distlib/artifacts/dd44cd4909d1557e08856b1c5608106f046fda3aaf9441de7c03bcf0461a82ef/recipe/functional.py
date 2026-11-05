from distlib.version import NormalizedVersion
assert NormalizedVersion('1.2.3') < NormalizedVersion('1.3.0')
assert NormalizedVersion('2.0') == NormalizedVersion('2.0.0')
print('CPG_FUNCTIONAL_OK:distlib:version-comparison')
