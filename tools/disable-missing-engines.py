import sys
import os
import yaml
import re

def disable_engine_in_text(yaml_content, engine_name):
    # Locate exactly one YAML sequence item at a time.  The previous pattern
    # treated every indented line as part of the first item, so a list of engine
    # entries became one giant block and the first ``disabled`` field could be
    # changed instead of the missing engine's field.
    lines = yaml_content.splitlines(keepends=True)
    item_pattern = re.compile(r"^(?P<indent>[ \t]*)-\s+name:\s*(?P<name>.*?)(?:\r?\n)?$")

    for start, line in enumerate(lines):
        item_match = item_pattern.match(line)
        if not item_match:
            continue

        try:
            parsed_name = yaml.safe_load(item_match.group('name').strip())
        except Exception:
            parsed_name = item_match.group('name').strip().strip("\"'")
        if parsed_name != engine_name:
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

        disabled_match = re.search(
            rf'(?m)^{re.escape(child_indent)}disabled:\s*([^\r\n]*)', block
        )
        if disabled_match:
            val = disabled_match.group(1).strip().lower()
            if val in ('true', 'yes', 'on', '1'):
                return yaml_content
            line_end = '\r\n' if block[disabled_match.end():].startswith('\r\n') else '\n' if block[disabled_match.end():].startswith('\n') else ''
            replacement = f"{child_indent}disabled: true{line_end}"
            new_block = block[:disabled_match.start()] + replacement + block[disabled_match.end() + len(line_end):]
        else:
            nl = '\r\n' if '\r\n' in block else '\n'
            insert_at = len(block_lines)
            while insert_at > 0 and not block_lines[insert_at - 1].strip():
                insert_at -= 1
            prefix = ''.join(block_lines[:insert_at])
            suffix = ''.join(block_lines[insert_at:])
            if prefix and not prefix.endswith(('\n', '\r')):
                prefix += nl
            new_block = prefix + f"{child_indent}disabled: true{nl}" + suffix

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

    try:
        config = yaml.safe_load(yaml_content)
    except Exception as e:
        print(f"Error parsing YAML: {e}")
        sys.exit(1)

    if not config or 'engines' not in config:
        print("No engines defined in settings.yml.")
        sys.exit(0)

    missing_engines = []
    for engine_entry in config.get('engines', []):
        name = engine_entry.get('name')
        if not name:
            continue
        engine_mod = engine_entry.get('engine', name)
        
        # Skip template or complex dynamic engines
        if engine_mod and re.match(r'^[a-z0-9_-]+$', engine_mod):
            mod_file = os.path.join(engines_dir, f"{engine_mod}.py")
            if not os.path.exists(mod_file):
                # If module is missing and not already disabled
                if not engine_entry.get('disabled'):
                    missing_engines.append((name, engine_mod))

    if not missing_engines:
        print("No missing engines detected.")
        sys.exit(0)

    modified_content = yaml_content
    for name, engine_mod in missing_engines:
        print(f"Engine module missing: {engine_mod} (name: {name}) - marking disabled in settings.yml")
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
