# Seeded bugs vs clean fixes — pallets/flask @ 3.1.0

Models: nomic-embed-text:latest, qwen2.5-coder:1.5b, qwen2.5-coder:7b. Generated 2026-10-20T08:37:18+00:00. Tests not run.

| Measure | Result |
|---|---|
| Planted bugs caught (medium/high on the changed line) | **70%** (14 of 20) |
| Clean merged fixes flagged medium/high (false alarms) | **30%** (6 of 20) |
| Clean merged fixes flagged high | 0% |
| Median seconds per review | 28.7 |

## Planted bugs

| File:line | Mutation | Change | Caught |
|---|---|---|---|
| `src/flask/cli.py:501` | invert is not None | `if value is not None:` → `if value is None:` | no |
| `src/flask/sansio/app.py:956` | invert is not None | `if rv is not None:` → `if rv is None:` | yes |
| `src/flask/sansio/blueprints.py:104` | invert is None | `if endpoint is None:` → `if endpoint is not None:` | yes |
| `src/flask/helpers.py:32` | and to or | `return bool(val and val.lower() not in {"0", "false", "no"})` → `return bool(val or val.lower() not in {"0", "false", "no"})` | no |
| `src/flask/app.py:445` | invert is not None | `if request is not None:` → `if request is None:` | no |
| `src/flask/sansio/blueprints.py:389` | invert is None | `key = name if key is None else f"{name}.{key}"` → `key = name if key is not None else f"{name}.{key}"` | no |
| `src/flask/blueprints.py:74` | invert is None | `if value is None:` → `if value is not None:` | yes |
| `src/flask/testing.py:65` | or to and | `http_host = app.config.get("SERVER_NAME") or "localhost"` → `http_host = app.config.get("SERVER_NAME") and "localhost"` | yes |
| `src/flask/config.py:117` | flip return False | `return False` → `return True` | yes |
| `src/flask/cli.py:1087` | or to and | `row.append((rule.host if host_matching else rule.subdomain) or "")` → `row.append((rule.host if host_matching else rule.subdomain) and "")` | yes |
| `src/flask/config.py:355` | drop not | `if not k.startswith(namespace):` → `if k.startswith(namespace):` | yes |
| `src/flask/sansio/blueprints.py:308` | flip != | `existing_at = f" '{name}'" if self_name != name else ""` → `existing_at = f" '{name}'" if self_name == name else ""` | yes |
| `src/flask/cli.py:1071` | drop not | `if not rules:` → `if rules:` | yes |
| `src/flask/json/provider.py:81` | drop not | `if not args and not kwargs:` → `if args and not kwargs:` | yes |
| `src/flask/json/provider.py:87` | or to and | `return args or kwargs` → `return args and kwargs` | no |
| `src/flask/app.py:1194` | flip == | `if len_rv == 3:` → `if len_rv != 3:` | yes |
| `src/flask/config.py:297` | flip return False | `return False` → `return True` | yes |
| `src/flask/sansio/app.py:641` | and to or | `if "OPTIONS" not in methods and self.config["PROVIDE_AUTOMATIC_OPTIONS"]:` → `if "OPTIONS" not in methods or self.config["PROVIDE_AUTOMATIC_OPTIONS"]:` | no |
| `src/flask/logging.py:73` | and to or | `if app.debug and not logger.level:` → `if app.debug or not logger.level:` | yes |
| `src/flask/app.py:358` | flip == | `if mode == "rb":` → `if mode != "rb":` | yes |

## Clean fixes

| Commit | Subject | Flagged |
|---|---|---|
| `4995a775df` | fix subdomain_matching=False behavior | no |
| `df201ed152` | fix js example test | no |
| `40b78fa2ea` | fix min python for pip-compile | no |
| `1af8f95785` | fix super call in list comprehension | no |
| `5fcc999b7d` | fix create release action | yes |
| `da3a0ddfe2` | fix slsa generator version | no |
| `bda295d37f` | fix use of importlib.util.find_spec | yes |
| `0ec9192cf2` | fix importing Markup from flask | no |
| `d7b6c1f670` | Fix subdomain inheritance for nested blueprints. | no |
| `a6a7a57380` | fix default value of app.env | no |
| `095651be9e` | fix has_app_context and has_request_context | yes |
| `3ba37d2afe` | fix uninstalled package tests under tox | no |
| `b707bf443a` | Preserve HttpOnly flag when deleting session cookie | no |
| `426a1e25b7` | fix pytest 7 warnings | yes |
| `633449a36c` | fix error message | no |
| `46b39e2698` | fix errorhandler type check | yes |
| `6a4bf9eec1` | use exception chaining | no |
| `166a2a6207` | Fix callback order for nested blueprints | no |
| `a44c722860` | Fix registering a blueprint twice with differing names | no |
| `a960236117` | Fix type annotation for `before_request` and `before_app_request` deco | yes |
