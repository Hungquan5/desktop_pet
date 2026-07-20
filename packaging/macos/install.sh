#!/bin/sh
set -eu

prefix="${HOME}/Applications/VlaPet"
wheel=""
mode="install"
models="false"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --wheel) wheel="$2"; shift 2 ;;
    --prefix) prefix="$2"; shift 2 ;;
    --models) models="true"; shift ;;
    --rollback) mode="rollback"; shift ;;
    --uninstall) mode="uninstall"; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

releases="${prefix}/releases"
current="${prefix}/current"
previous="${prefix}/previous"
if [ "$mode" = "uninstall" ]; then
  rm -rf "$prefix"
  echo "Uninstalled momo-chan; Library/Application Support data was preserved."
  exit 0
fi
if [ "$mode" = "rollback" ]; then
  [ -L "$previous" ] || { echo "No previous release" >&2; exit 2; }
  old_current="$(readlink "$current")"
  old_previous="$(readlink "$previous")"
  ln -sfn "$old_previous" "${current}.tmp"
  mv -f "${current}.tmp" "$current"
  ln -sfn "$old_current" "$previous"
  echo "Rolled back momo-chan."
  exit 0
fi
[ -f "$wheel" ] || { echo "--wheel must name an existing wheel" >&2; exit 2; }
release="${releases}/release-$(date +%s)-$$"
python3 -m venv "$release"
package="$wheel"
if [ "$models" = "true" ]; then package="${wheel}[models]"; fi
"${release}/bin/python" -m pip install "$package"
mkdir -p "$prefix"
if [ -L "$current" ]; then ln -sfn "$(readlink "$current")" "$previous"; fi
ln -s "$release" "${current}.tmp"
mv -f "${current}.tmp" "$current"
mkdir -p "${prefix}/VlaPet.app/Contents/MacOS"
printf '%s\n' '#!/bin/sh' 'exec "'"${current}"'/bin/momo-chan" "$@"' > "${prefix}/VlaPet.app/Contents/MacOS/momo-chan"
cp "${prefix}/VlaPet.app/Contents/MacOS/momo-chan" "${prefix}/VlaPet.app/Contents/MacOS/vla-pet"
chmod 755 "${prefix}/VlaPet.app/Contents/MacOS/momo-chan" "${prefix}/VlaPet.app/Contents/MacOS/vla-pet"
echo "Installed unsigned developer app into $prefix; public releases require Developer ID signing and notarization."
