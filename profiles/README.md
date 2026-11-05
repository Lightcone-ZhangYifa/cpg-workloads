# Complete dependency profiles

Generated JSON manifests appear here only when every archive in an original dependency context or a package-specific transitive closure has a verified public Release receipt. Each manifest is an ordinary Compiler Playground repository index with one unambiguous archive per full package identity.

Use the selected profile manifest for dependency resolution. The root manifest lists canonical software for discovery and reports ready and pending profiles separately; dependency variants stay outside its default package list. Original identity inventories are retained in `catalog/dependency-profiles/`. No build or functional execution is implied by a profile becoming available.
