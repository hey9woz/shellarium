"""Conservative portable-config policy. Errors never include input values."""
import math
import re
import tomllib
import unicodedata
from urllib.parse import urlsplit


class Invalid(Exception):
    pass


NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
SECRET = re.compile(
    r"-----BEGIN (?:[A-Z ]*PRIVATE KEY|PGP PRIVATE KEY BLOCK)-----|"
    r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{12,}|github_pat_[A-Za-z0-9_]{12,}|"
    r"AKIA[A-Z0-9]{16}|xox[baprs]-[A-Za-z0-9-]{12,})|"
    r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
)
ASSIGNMENT = re.compile(
    r"(?im:(?:api[_ -]?key|(?:access[_ -]?)?token|passw(?:or)?d|(?:client[_ -]?)?secret|credential|private[_ -]?key|authorization)[\"']?"
    r"\s*[=:]\s*[\"']?[^\s\"',}]+)"
)
ROOT_STR = {
    "model", "review_model", "model_provider", "model_reasoning_effort",
    "model_reasoning_summary", "model_verbosity", "approval_policy", "sandbox_mode",
    "personality", "web_search", "service_tier",
}
ROOT_BOOL = {"hide_agent_reasoning", "show_raw_agent_reasoning", "check_for_update_on_startup",
             "suppress_unstable_features_warning", "disable_paste_burst"}
ROOT_INT = {"model_context_window", "model_auto_compact_token_limit", "project_doc_max_bytes"}
MCP_STR = {"command", "url", "cwd", "environment_id", "auth", "bearer_token_env_var",
           "default_tools_approval_mode", "startup_readiness"}
MCP_LIST = {"args", "enabled_tools", "disabled_tools"}
MCP_BOOL = {"enabled", "required"}
MCP_NUM = {"startup_timeout_sec", "tool_timeout_sec"}


def reject(file, path, reason):
    # Unknown keys can themselves be secrets; report the location, not the name.
    raise Invalid(f"{file}: {path}: {reason} (values suppressed)")


def scan(text, file, assignments=True):
    if (any(unicodedata.category(c) == "Cc" and c not in "\n\r\t" for c in text)
            or re.search(r"\r(?!\n)|[\u202a-\u202e\u2066-\u2069]", text)):
        reject(file, "text", "terminal control characters are not allowed")
    if SECRET.search(text) or (assignments and ASSIGNMENT.search(text)):
        reject(file, "text", "possible credential or private key")
    # Catch opaque credentials even in prose/positional arguments. This is a
    # heuristic, not proof that arbitrary text contains no secret.
    for token in re.findall(r"[A-Za-z0-9_+/=-]{32,}", text):
        probabilities = [token.count(c) / len(token) for c in set(token)]
        entropy = -sum(p * math.log2(p) for p in probabilities)
        if entropy > 4.3 and any(c.isdigit() for c in token) and any(c.isalpha() for c in token):
            reject(file, "text", "possible opaque credential")


def variable(value, file, path):
    if not isinstance(value, str) or not NAME.fullmatch(value):
        reject(file, path, "expected an environment variable NAME, not a value or interpolation")


def portable(value, file, path):
    if not isinstance(value, str) or value.startswith(("/", "~", "file:", "\\")) or re.match(r"^[A-Za-z]:", value):
        reject(file, path, "machine-specific or invalid path")
    if re.search(r"(?:^|[=\s])(?:/home/|/Users/|~/)", value):
        reject(file, path, "machine-specific path")


def url(value, file, path):
    if not isinstance(value, str):
        reject(file, path, "expected URL")
    try:
        parsed = urlsplit(value)
        valid = parsed.scheme in {"https", "http"} and parsed.hostname and not (
            parsed.username or parsed.password or parsed.query or parsed.fragment)
    except ValueError:
        valid = False
    if not valid:
        reject(file, path, "URL must not contain user info, query parameters or fragments")


def expect(value, kind, file, path):
    if type(value) is not kind:
        reject(file, path, f"expected {kind.__name__}")


def string_list(value, file, path):
    expect(value, list, file, path)
    if any(not isinstance(item, str) for item in value):
        reject(file, path, "expected an array of strings")


def mcp(server, file):
    path = "mcp_servers.<server>"
    expect(server, dict, file, path)
    for key, value in server.items():
        item = path + "." + key if key in MCP_STR | MCP_LIST | MCP_BOOL | MCP_NUM | {"env_vars", "env_http_headers", "tools"} else path + ".<unsupported>"
        if key in MCP_STR:
            expect(value, str, file, item)
            if key == "bearer_token_env_var":
                variable(value, file, item)
            elif key == "url":
                url(value, file, item)
            elif key in {"command", "cwd"}:
                portable(value, file, item)
                if key == "command" and value in {"sh", "bash", "zsh", "fish", "env"}:
                    reject(file, item, "shell wrappers cannot be validated safely")
        elif key in MCP_LIST:
            string_list(value, file, item)
            if key == "args":
                for arg in value:
                    portable(arg, file, item)
                    for address in re.findall(r'[A-Za-z][A-Za-z0-9+.-]*://[^\s"\']+', arg):
                        url(address, file, item)
                    if re.match(r"(?i)^--(?:key|auth|credentials?|user(?:name)?|login|bearer|passwd)(?:=|$)", arg):
                        reject(file, item, "literal authentication arguments are not allowed")
                    if re.match(r"^(?:-[ce](?:[^-].*)?|--(?:eval|command)(?:=.*)?)$", arg) or re.search(r"(?i)(?:token|password|secret|api[-_]?key|authorization)", arg):
                        reject(file, item, "credential arguments are not allowed; use environment forwarding")
        elif key in MCP_BOOL:
            expect(value, bool, file, item)
        elif key in MCP_NUM:
            if (type(value) not in {int, float}
                    or (type(value) is int and not 0 <= value <= 2**63 - 1)
                    or (type(value) is float and (not math.isfinite(value) or value < 0))):
                reject(file, item, "expected a nonnegative finite number")
        elif key == "env_vars":
            expect(value, list, file, item)
            names = []
            for entry in value:
                if isinstance(entry, dict):
                    if set(entry) - {"name", "source"} or entry.get("source", "local") not in ("local", "remote"):
                        reject(file, item, "invalid environment source")
                    entry = entry.get("name")
                variable(entry, file, item)
                names.append(entry)
            if len(names) != len(set(names)):
                reject(file, item, "duplicate environment variable")
        elif key == "env_http_headers":
            expect(value, dict, file, item)
            for name in value.values():
                variable(name, file, item)
        elif key == "tools":
            expect(value, dict, file, item)
            for tool in value.values():
                expect(tool, dict, file, item)
                for option, setting in tool.items():
                    if option == "approval_mode":
                        expect(setting, str, file, item)
                    elif option == "output_token_limit":
                        expect(setting, int, file, item)
                    else:
                        reject(file, item, "unsupported tool setting")
        else:
            reject(file, path + ".<unsupported>", "unsupported or literal-credential setting; env/http_headers/oauth secrets are not distributable")


def config(data, file, profile=False):
    for key, value in data.items():
        path = key if key in ROOT_STR | ROOT_BOOL | ROOT_INT | {"profiles", "features", "history", "sandbox_workspace_write", "mcp_servers", "model_providers"} else "<unsupported>"
        if key in ROOT_STR:
            expect(value, str, file, path)
        elif key in ROOT_BOOL:
            expect(value, bool, file, path)
        elif key in ROOT_INT:
            expect(value, int, file, path)
        elif key == "profiles" and not profile:
            expect(value, dict, file, path)
            for settings in value.values():
                expect(settings, dict, file, "profiles.<profile>")
                config(settings, file, profile=True)
        elif key == "features":
            expect(value, dict, file, path)
            for setting in value.values():
                expect(setting, bool, file, path)
        elif key == "history":
            expect(value, dict, file, path)
            for option, setting in value.items():
                if option == "persistence":
                    expect(setting, str, file, path)
                elif option == "max_bytes":
                    expect(setting, int, file, path)
                else:
                    reject(file, path, "unsupported history setting")
        elif key == "sandbox_workspace_write":
            expect(value, dict, file, path)
            for option, setting in value.items():
                if option == "writable_roots":
                    string_list(setting, file, path)
                    for root in setting:
                        portable(root, file, path)
                elif option in {"network_access", "exclude_tmpdir_env_var", "exclude_slash_tmp"}:
                    expect(setting, bool, file, path)
                else:
                    reject(file, path, "unsupported sandbox setting")
        elif key == "mcp_servers":
            expect(value, dict, file, path)
            for server in value.values():
                mcp(server, file)
        elif key == "model_providers":
            expect(value, dict, file, path)
            for provider in value.values():
                expect(provider, dict, file, path)
                for option, setting in provider.items():
                    if option in {"name", "wire_api", "env_key", "base_url"}:
                        expect(setting, str, file, path)
                        if option == "env_key":
                            variable(setting, file, path)
                        elif option == "base_url":
                            url(setting, file, path)
                    elif option == "requires_openai_auth":
                        expect(setting, bool, file, path)
                    else:
                        reject(file, path, "unsupported provider setting")
        else:
            reject(file, path, "unsupported distribution setting")


def validate(name, content):
    try:
        text = content.decode("utf-8")
    except UnicodeError:
        reject(name, "text", "expected UTF-8")
    scan(text, name, assignments=name != "config.toml")
    if name == "config.toml":
        try:
            data = tomllib.loads(text)
        except tomllib.TOMLDecodeError:
            reject(name, "TOML", "invalid TOML")
        config(data, name)
        # Check scalar contents, not TOML key/value syntax: header mappings such
        # as "X-API-Key" = "TOKEN_NAME" are legitimate environment references.
        def strings(value):
            if isinstance(value, str):
                scan(value, name)
            elif isinstance(value, dict):
                for item in value.values():
                    strings(item)
            elif isinstance(value, list):
                for item in value:
                    strings(item)
        strings(data)
        for line in text.splitlines():
            if "#" in line:
                scan(line.partition("#")[2], name)
    return text
