### Surface detail

Paint the model's surface detail. Don't change its shape, rig, or colors unless asked. Paint it in model.py from the geometry, after the parts are built and colored, so the script still builds the whole model from an empty scene, and a later change to a part repaints it.

- One grayscale texture, saved beside model.glb as model-detail.png: an 8 bit grayscale PNG with no color space chunks, since it holds amounts rather than colors. Mid gray is neutral. A renderer multiplies the base color by twice the detail, so darker darkens and lighter brightens, in every color scheme.
- Declare it on the material, as the check-3d-model skill describes. glTF has no place for it, so the exported material otherwise stays as it was. A model with no material yet gets one plain material to declare it on.
- On the second UV set, unwrap the faces that get detail at one texel density, kept as a named constant: about a texel per pixel at the largest size on screen, unless the project says otherwise. Faces without detail all point at one neutral patch. Pad each island by painting a few texels past its faces, so mipmaps don't bleed. Keep an island whole where marks cross its edges, such as a round part's sides unrolled into one strip. Use the smallest power of two texture that fits, square or not.
- Paint from positions on the model rather than on the texture, so lines that cross faces line up, and with 3D noise, so marks carry around edges. Seed the noise, so every build paints the same marks.
- Size marks in meters, and lines in texels, at least a few texels wide, so they fade with mipmaps instead of flickering. A mark that stops partway across a face shows its edge, so fade it out or run it to an edge.
- Keep each kind of mark's sizes, strengths, and seeds as named constants at the top of model.py, so a request can change one kind.

Paint what the thing would show from how it is made and used: seams where panels meet, fasteners, vents, highlights along outer edges, soft shading where parts meet, wear where it is handled or knocked, and soot or grime where it would gather. The project's guidance says how much. Make marks strong enough to read on their role's color at the largest size on screen, since darkening shows little on dark colors and brightening clips on light ones. Leave out shading the lighting already does. Leave faces neutral where detail would not show or should not be, such as glowing faces and deep recesses. The detail only lightens or darkens, so a mark in another color needs a face of its own with its role, which is part of coloring.

For renders, apply a copy of the material that multiplies its base color by twice the detail on the second UV set, after export, so they show the detail as a renderer will. Judge it at the sizes on screen, since a render larger than the largest size magnifies the texels and looks soft.

Finish by listing what you painted where, and the constants that set each kind.
