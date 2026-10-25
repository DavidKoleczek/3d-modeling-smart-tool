### Coloring

Color the model by role. Don't change its shape or rig unless asked, apart from cutting a face where a color changes. Color it in model.py after the parts are built, so the script still builds the whole model from an empty scene, and a later change to a part keeps its colors.

- One material on every mesh. Its base color texture is a palette, an image with one column for each role and one row for each scheme, embedded in model.glb. Sample it with nearest filtering and clamped edges, Closest interpolation and Extend in Blender, so swatches never blend.
- Every corner of a face has the same UV on the first UV set: the center of its role's swatch in the default scheme's row. Another scheme is another row, which an app shows by moving the UVs a row at a time. Leave the second UV set free.
- Use the project's roles and schemes, in its order, where it names them. Otherwise pick a few broad roles from the parts and the request, since changing the layout later means recoloring every model made with it.
- Colors are sRGB, as a fully lit face shows them. Colors sampled from shaded concept art come out darker than meant, so take them from its lit faces.
- Roles that glow go in an emission palette of the same layout, black for every other role, as the material's emissive texture.
- Declare the palette's roles and schemes on the material, as the check-3d-model skill describes.
- Keep the roles and each scheme's colors as named constants at the top of model.py. A new scheme is a new row. Replace a row only when asked, so the old one stays to compare.

Changing which role a part has is part of coloring, such as a handle going to dark metal to read as steel. A color on part of a face needs a face of its own with its role. A line too thin for that, or a change of shade, belongs to surface detail, which comes later and only lightens or darkens, so a hue the palette lacks needs a role.

Render with Blender's Standard view transform, since AgX and Filmic shift the colors, and the renders are where the colors are judged.

Finish by listing each role's color in each scheme you set or changed.
