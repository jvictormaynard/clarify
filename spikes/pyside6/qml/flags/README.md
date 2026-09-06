# Flag assets

Vendored from [lipis/flag-icons](https://github.com/lipis/flag-icons) at commit
`086f7e97d657358203916dbe84f61c2bccaa81eb`, using the `flags/4x3` SVG files.

| Clarify language asset | Upstream country asset |
| --- | --- |
| en.svg | us.svg (United States) |
| pt.svg | br.svg (Brazil) |
| es.svg | es.svg (Spain) |
| de.svg | de.svg (Germany) |
| ru.svg | ru.svg (Russia) |

The outer contours have been adapted to rounded corners directly in the SVG
paths. US stripe and star geometry is clipped into those paths at authoring time;
no runtime SVG clipPath or Canvas is required. RoundedFlag.qml uses Qt Quick
Image with an explicit source size based on display density and shell scale.
The flags retain their 4:3 artwork and the existing language mapping. Language
labels remain visible and accessible.

Only these five SVGs are included. No npm package, CSS, CDN or runtime download
is required. Copyright and permission notice: `licenses/flag-icons-MIT.txt`
(packaged with the application's third-party licenses).
