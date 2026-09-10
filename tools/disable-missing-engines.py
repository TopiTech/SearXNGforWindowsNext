import os
import re
import sys

try:
    import yaml
except ImportError:
    yaml = None


def _unquote(s):
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    return s


def parse_engines_fallback(yaml_content):
    """Parse engine entries using only the standard library.

    Extracts name, engine, and inactive fields for each item in the top-level
    ``engines:`` sequence without requiring PyYAML.
    """
    lines = yaml_content.splitlines()
    in_engines = False
    engines_indent = None
    item_indent = None
    engines = []
    current_item = None

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue

        indent = len(line) - len(line.lstrip(' \t'))

        if not in_engines:
            m = re.match(r'^([ \t]*)engines\s*:', line)
            if m:
                in_engines = True
                engines_indent = len(m.group(1))
            continue

        # If indent is <= engines_indent and not a list item, engines section ended
        if indent <= engines_indent and not line.lstrip().startswith('-'):
            break

        # Check for start of a new list item at engines list level
        item_m = re.match(r'^([ \t]*)-\s*(.*)$', line)
        if item_m and (item_indent is None or len(item_m.group(1)) == item_indent or (item_indent is None and len(item_m.group(1)) > engines_indent)):
            if current_item is not None and 'name' in current_item:
                if 'engine' not in current_item:
                    current_item['engine'] = current_item['name']
                engines.append(current_item)
            current_item = {}
            item_indent = len(item_m.group(1))
            rest = item_m.group(2).strip()
            if rest:
                kv_m = re.match(r'^([a-zA-Z0-9_-]+)\s*:\s*(.*)$', rest)
                if kv_m:
                    k = kv_m.group(1)
                    v = re.split(r'\s+#', kv_m.group(2), maxsplit=1)[0].strip()
                    v = _unquote(v)
                    if k == 'inactive':
                        current_item[k] = v.lower() in ('true', 'yes', 'on', '1')
                    else:
                        current_item[k] = v
            continue

        if current_item is not None and indent > item_indent:
            kv_m = re.match(r'^[ \t]*([a-zA-Z0-9_-]+)\s*:\s*(.*)$', line)
            if kv_m:
                k = kv_m.group(1)
                v = re.split(r'\s+#', kv_m.group(2), maxsplit=1)[0].strip()
                v = _unquote(v)
                if k == 'inactive':
                    current_item[k] = v.lower() in ('true', 'yes', 'on', '1')
                else:
                    current_item[k] = v

    if current_item is not None and 'name' in current_item:
        if 'engine' not in current_item:
            current_item['engine'] = current_item['name']
        engines.append(current_item)

    return engines


def extract_engines(yaml_content):
    """Extract engine list (name, engine, inactive) from YAML content.

    Prefers PyYAML if installed; falls back to standard-library parser so
    bootstrap and upstream sync succeed in environments without PyYAML.
    """
    if yaml is not None:
        try:
            config = yaml.safe_load(yaml_content)
            if config and isinstance(config, dict) and 'engines' in config:
                return config.get('engines') or []
        except (yaml.YAMLError, ValueError, TypeError, AttributeError):
            pass
    return parse_engines_fallback(yaml_content)


def disable_engine_in_text(yaml_content, engine_name):
    """Mark an engine as inactive without changing its user preference state.

    ``disabled`` means "off by default" in SearXNG and users may enable such
    an engine from Preferences.  A missing implementation module must instead
    be ``inactive`` so it is removed from the available engine list and cannot
    cause a startup failure.
    """
    # Locate exactly one YAML sequence item at a time.  The previous pattern
    # treated every indented line as part of the first item, so a list of engine
    # entries became one giant block and the first ``disabled`` field could be
    # changed instead of the missing engine's field.
    lines = yaml_content.splitlines(keepends=True)
    item_pattern = re.compile(r"^(?P<indent>[ \t]*)-\s+(?:name:\s*(?P<name>[^\r\n]*)|(?P<other>[^\r\n]*))(?:\r?\n)?$")

    for start, line in enumerate(lines):
        item_match = item_pattern.match(line)
        if not item_match:
            continue

        item_indent = item_match.group('indent')
        end = start + 1
        while end < len(lines):
            candidate = lines[end]
            if re.match(rf"^{re.escape(item_indent)}-\s+", candidate):
                break
            if candidate.strip() and not candidate.lstrip().startswith('#'):
                candidate_indent = candidate[:len(candidate) - len(candidate.lstrip(' \t'))]
                if len(candidate_indent) <= len(item_indent):
                    break
            end += 1

        raw_name = item_match.group('name')
        if raw_name is None:
            # Look for a nested `name:` within this list item block
            name_m = re.search(r'(?m)^[ \t]+name:\s*([^\r\n#]*)', ''.join(lines[start:end]))
            if name_m:
                raw_name = name_m.group(1).strip()

        if not raw_name:
            continue

        parsed_name = None
        if yaml is not None:
            try:
                parsed_name = yaml.safe_load(raw_name.strip())
            except (yaml.YAMLError, ValueError, TypeError, AttributeError):
                pass
        if parsed_name is None:
            parsed_name = _unquote(raw_name.strip())
        if parsed_name != engine_name:
            continue

        block = ''.join(lines[start:end])
        block_lines = block.splitlines(keepends=True)
        child_indent = None
        for child_line in block_lines[1:]:
            if child_line.strip() and not child_line.lstrip().startswith('#'):
                child_indent = child_line[:len(child_line) - len(child_line.lstrip(' \t'))]
                if len(child_indent) > len(item_indent):
                    break
        if child_indent is None or len(child_indent) <= len(item_indent):
            child_indent = item_indent + '  '

        inactive_match = re.search(
            rf'(?m)^{re.escape(child_indent)}inactive:\s*([^\r\n]*)', block
        )
        if inactive_match:
            val = inactive_match.group(1).strip().lower()
            if val in ('true', 'yes', 'on', '1'):
                return yaml_content
            line_end = '\r\n' if block[inactive_match.end():].startswith('\r\n') else '\n' if block[inactive_match.end():].startswith('\n') else ''
            replacement = f"{child_indent}inactive: true{line_end}"
            new_block = block[:inactive_match.start()] + replacement + block[inactive_match.end() + len(line_end):]
        else:
            nl = '\r\n' if '\r\n' in block else '\n'
            insert_at = len(block_lines)
            while insert_at > 0 and not block_lines[insert_at - 1].strip():
                insert_at -= 1
            prefix = ''.join(block_lines[:insert_at])
            suffix = ''.join(block_lines[insert_at:])
            if prefix and not prefix.endswith(('\n', '\r')):
                prefix += nl
            new_block = prefix + f"{child_indent}inactive: true{nl}" + suffix

        return ''.join(lines[:start]) + new_block + ''.join(lines[end:])

    return yaml_content


def main():
    if len(sys.argv) < 3:
        print("Usage: disable-missing-engines.py <settings_path> <engines_dir>")
        sys.exit(1)

    settings_path = os.path.abspath(sys.argv[1])
    engines_dir = os.path.abspath(sys.argv[2])

    if not os.path.exists(settings_path):
        print(f"settings.yml not found at: {settings_path}")
        sys.exit(0)

    if not os.path.exists(engines_dir):
        print(f"engines directory not found at: {engines_dir}")
        sys.exit(1)

    with open(settings_path, 'r', encoding='utf-8') as f:
        yaml_content = f.read()

    engines = extract_engines(yaml_content)

    if not engines:
        print("No engines defined in settings.yml.")
        sys.exit(0)

    missing_engines = []
    for engine_entry in engines:
        name = engine_entry.get('name')
        if not name:
            continue
        engine_mod = engine_entry.get('engine', name)

        # Skip template or complex dynamic engines
        if engine_mod and re.match(r'^[a-z0-9_-]+$', engine_mod):
            mod_file = os.path.join(engines_dir, f"{engine_mod}.py")
            pkg_init = os.path.join(engines_dir, engine_mod, "__init__.py")
            if (
                not os.path.exists(mod_file)
                and not os.path.exists(pkg_init)
                and not engine_entry.get('inactive')
            ):
                # If a module is missing, it must be removed rather than merely
                # disabled: disabled engines are intentionally still loadable.
                missing_engines.append((name, engine_mod))

    if not missing_engines:
        print("No missing engines detected.")
        sys.exit(0)

    modified_content = yaml_content
    for name, engine_mod in missing_engines:
        print(f"Engine module missing: {engine_mod} (name: {name}) - marking inactive in settings.yml")
        modified_content = disable_engine_in_text(modified_content, name)

    if modified_content != yaml_content:
        # Write back updated content while preserving all formatting and comments
        with open(settings_path, 'w', encoding='utf-8', newline='\n') as f:
            f.write(modified_content)
        print("settings.yml updated successfully (comments preserved).")
    else:
        print("No changes made to settings.yml.")


if __name__ == "__main__":
    main()
