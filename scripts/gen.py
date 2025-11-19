
#!/usr/bin/env python3
import subprocess
import re
from pathlib import Path

# Paths
SCRIPT_DIR = Path(__file__).parent
PROTO_DIR = SCRIPT_DIR / "proto"
OUTPUT_DIR = SCRIPT_DIR.parent / "libspot" / "proto"


def to_pascal_case(name: str) -> str:
    """Convert snake_case or kebab-case to PascalCase"""
    clean = name.replace("-", "_")  # treat dashes like underscores
    return ''.join(word.title() for word in clean.split('_'))


def generate_proto_files():
    # Ensure output directory exists
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Find all .proto files
    proto_files = list(PROTO_DIR.rglob("*.proto"))

    for proto_file in proto_files:
        # Calculate relative path from proto directory
        rel_path = proto_file.relative_to(PROTO_DIR)

        # Original stem (filename without extension)
        file_stem = proto_file.stem

        # PascalCase version
        pascal_name = to_pascal_case(file_stem)
        output_filename = f"{pascal_name}_pb2.py"
        output_path = OUTPUT_DIR / rel_path.parent / output_filename
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Run protoc (always snake_case output)
        cmd = [
            "protoc",
            f"--proto_path={PROTO_DIR}",
            f"--python_out={OUTPUT_DIR}",
            str(rel_path)
        ]

        print(f"Generating {output_path}...")
        try:
            subprocess.run(cmd, check=True)

            # Snake_case output from protoc
            generated_file = OUTPUT_DIR / rel_path.parent / f"{file_stem.replace('-', '_')}_pb2.py"

            # Rename to PascalCase if needed
            if generated_file.exists() and generated_file != output_path:
                generated_file.rename(output_path)

            # 🔧 Fix imports inside the generated file
            if output_path.exists():
                fix_imports(output_path)

            print(f"✅ Successfully generated {output_path}")
        except subprocess.CalledProcessError as e:
            print(f"❌ Error generating {output_path}: {e}")
        except Exception as e:
            print(f"⚠️ Unexpected error processing {proto_file}: {e}")


def fix_imports(py_file: Path):
    """Rewrite imports inside _pb2.py files so they use PascalCase + libspot.proto"""
    text = py_file.read_text()

    def repl(match):
        module_name = match.group(1)  # e.g. connectivity_pb2
        alias = match.group(2)        # e.g. connectivity__pb2
        # Convert base name before _pb2 into PascalCase
        base = module_name[:-4]  # remove _pb2
        pascal = ''.join(word.title() for word in base.replace("-", "_").split("_"))
        return f"from libspot.proto import {pascal}_pb2 as {alias}"

    # Handle both flat and nested imports
    text = re.sub(
        r"^(?:import|from [\w\.]+ import) (\w+_pb2) as (\w+__pb2)",
        repl,
        text,
        flags=re.M,
    )

    py_file.write_text(text)
    print(f"🔧 Fixed imports in {py_file.name}")


if __name__ == "__main__":
    generate_proto_files()
    print("🎉 Proto file generation complete!")
