# Vendored libraries

`three.min.js` is three.js r159 (MIT, see `THREE-LICENSE`), the last release that
still ships a classic script build. A classic script rather than an ES module because
the town must keep working when `web/index.html` is opened straight from disk
(`file://`), where browsers refuse to load modules. Vendored rather than loaded from a
CDN because `start.sh` has to work without an internet connection.

One change to the upstream file: its first line, a `console.warn` announcing that the
classic build is deprecated, is replaced by `void 0,`. Nothing else is touched.

    curl -sSfL -o three.min.js https://cdn.jsdelivr.net/npm/three@0.159.0/build/three.min.js
