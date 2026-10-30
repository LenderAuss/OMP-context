# Generated from versions.lock.json; do not edit by hand.
kit_uv_asset() {
  case "$1" in
    aarch64-apple-darwin)
      KIT_UV_URL='https://github.com/astral-sh/uv/releases/download/0.13.6/uv-aarch64-apple-darwin.tar.gz'
      KIT_UV_SHA256='60fbd5c8a1ed681845eea28d9d622fcde03c51e91a43465b64a1e17db1ed3472'
      ;;
    aarch64-unknown-linux-gnu)
      KIT_UV_URL='https://github.com/astral-sh/uv/releases/download/0.13.6/uv-aarch64-unknown-linux-gnu.tar.gz'
      KIT_UV_SHA256='229e194255c7958d86d56e8790d969a6f74736592133f0dfd0076f754c642c1d'
      ;;
    aarch64-unknown-linux-musl)
      KIT_UV_URL='https://github.com/astral-sh/uv/releases/download/0.13.6/uv-aarch64-unknown-linux-musl.tar.gz'
      KIT_UV_SHA256='819692e404d23e5aae6bc44c0e260f1f5492fd1910ab4693b2c650f926dbe800'
      ;;
    x86_64-apple-darwin)
      KIT_UV_URL='https://github.com/astral-sh/uv/releases/download/0.13.6/uv-x86_64-apple-darwin.tar.gz'
      KIT_UV_SHA256='63ba17fdda55ad1a230d4b37fc6017ffa10c23688c83818bd3bfdf914c652a02'
      ;;
    x86_64-unknown-linux-gnu)
      KIT_UV_URL='https://github.com/astral-sh/uv/releases/download/0.13.6/uv-x86_64-unknown-linux-gnu.tar.gz'
      KIT_UV_SHA256='f29c3e94ffabd7e6f3ba521dba169a9b7ec12100bf3257087f0f24f6123f3645'
      ;;
    x86_64-unknown-linux-musl)
      KIT_UV_URL='https://github.com/astral-sh/uv/releases/download/0.13.6/uv-x86_64-unknown-linux-musl.tar.gz'
      KIT_UV_SHA256='5d61f26b6c7213779eda90edc6971ea6b0b796bfb8d49a574c8ad69b59838548'
      ;;
    *) echo "Unsupported uv target: $1" >&2; exit 1 ;;
  esac
}
