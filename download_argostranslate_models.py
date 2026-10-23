"""
scripts/download_argostranslate_models.py

Downloads and installs Argos Translate package files locally for:
- Hebrew (he) <-> English (en)
- Greek (el) <-> English (en)
"""

import argostranslate.package
import argostranslate.translate


def setup_argos_models():
    print("1. Updating Argos Translate package index...")
    argostranslate.package.update_package_index()

    available_packages = argostranslate.package.get_available_packages()

    # Defined bidirectional pairs: (from_code, to_code)
    language_pairs = [
        ("he", "en"),  # Hebrew to English
        ("en", "he"),  # English to Hebrew
        ("el", "en"),  # Greek to English
        ("en", "el"),  # English to Greek
    ]

    print("\n2. Downloading and installing language packages...")
    for from_code, to_code in language_pairs:
        print(f"\nSearching for pair: {from_code} -> {to_code}...")
        pkg = next(
            (
                x
                for x in available_packages
                if x.from_code == from_code and x.to_code == to_code
            ),
            None,
        )

        if pkg:
            print(f"Downloading {from_code} -> {to_code}...")
            try:
                download_path = pkg.download()
                argostranslate.package.install_from_path(download_path)
                print(f"✅ Successfully installed {from_code} -> {to_code}")
            except Exception as e:
                print(
                    f"⚠️  Could not install {from_code} -> {to_code} via package index: {e}"
                )
        else:
            print(
                f"⚠️  Language pair {from_code} -> {to_code} not found in index."
            )

    print("\n==========================================")
    print("Argos Translate models installation complete!")
    print("==========================================")


if __name__ == "__main__":
    setup_argos_models()