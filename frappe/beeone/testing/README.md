# beeone black-box test tooling

Country-neutral helpers for suites that drive a running beeone site only through its public REST API:
`Api` / `ApiError` / `FeatureMissing`, `expect_error` / `expect_denied`, `money` / `qty` / `uid` / date helpers,
`Stack` (container, site, `bench`), `make_user`, `site_reachable`, `browser_session`.

The package imports nothing from frappe. A host-side suite loads it from a beeone checkout by path
(it must not import `frappe`, which needs the full server dependencies):

```python
spec = importlib.util.spec_from_file_location(
    "beeone_testing", f"{BEEONE_SRC}/frappe/beeone/testing/__init__.py",
    submodule_search_locations=[f"{BEEONE_SRC}/frappe/beeone/testing"])
```

An application suite subclasses `Api` (sets `BASE`, `ADMIN_PASSWORD`, `detect_missing`, `APP_METHOD_PREFIXES`),
keeps its own data (organizations, catalogs, messages) and its own environment variable names.
Country rules and data never belong here.
