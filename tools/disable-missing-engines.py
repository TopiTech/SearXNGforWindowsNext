import sys
import os
import yaml
import re

def disable_engine_in_text(yaml_content, engine_name):
    # Match any list item block starting with "  - " containing "name: engine_name"
    pattern = r"(?m)^([ \t]*-\s+[^\r\n]*\r?\n(?:[ \t]+[^\r\n]*\r?\n)*)"
    for match in re.finditer(pattern, yaml_content):
        block = match.group(1)
        if (re.search(rf"^[ \t]*-\s*name:\s*[\"']?{re.escape(engine_name)}[\"']?(?:\s|$)", block, re.M) or
                re.search(rf"^[ \t]+name:\s*[\"']?{re.escape(engine_name)}[\"']?(?:\s|$)", block, re.M)):

            # Check if disabled is already defined in this block
            disabled_match = re.search(r'(?m)^([ \t]+)disabled:\s*([^\r\n]*)', block)
            if disabled_match:
                val = disabled_match.group(2).strip().lower()
                if val in ('true', 'yes', 'on', '1'):
                    return yaml_content
                # Replace the existing disabled line with disabled: true
                new_block = (
                    block[:disabled_match.start()]
                    + f"{disabled_match.group(1)}disabled: true"
                    + block[disabled_match.end():]
                )
                return yaml_content[:match.start()] + new_block + yaml_content[match.end():]

            # Determine child indentation from the second line of the block
            lines = block.splitlines()
            child_indent = "    "
            for line in lines[1:]:
                if line.strip():
                    child_indent = line[:len(line) - len(line.lstrip())]
                    break

            # Insert disabled: true at the end of the block before any trailing empty lines
            last_valid_idx = len(lines) - 1
            while last_valid_idx >= 0 and not lines[last_valid_idx].strip():
                last_valid_idx -= 1

            if last_valid_idx >= 0:
                lines.insert(last_valid_idx + 1, f"{child_indent}disabled: true")

            nl = "\r\n" if "\r\n" in block else "\n"
            new_block = nl.join(lines) + nl
            return yaml_content[:match.start()] + new_block + yaml_content[match.end():]

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
