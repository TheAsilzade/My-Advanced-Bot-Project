import argostranslate.package

print("Updating package index...")
argostranslate.package.update_package_index()

available_packages = argostranslate.package.get_available_packages()

package = next(
    filter(lambda x: x.from_code == "tr" and x.to_code == "en", available_packages)
)

print("Downloading & installing Turkish -> English model...")
argostranslate.package.install_from_path(package.download())

print("DONE ")