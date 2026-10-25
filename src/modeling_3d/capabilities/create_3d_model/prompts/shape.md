Build the model from named parts with its dimensions as named constants at the top of model.py, so a later request can change one part without touching the rest or losing quality.

Leave out materials, colors, and textures unless the request asks for them, since normally rigging, color, and surface detail come as separate stages after this one. Record each face's role in model.py as you build it instead, such as main body, trim, or glow, using the project's roles where it has them, so colors and surface detail can later be assigned by role without changing the shape. Where a color changes partway across a part, such as a lamp, a stripe, or a trim line, build that edge into the part and record the role of the faces inside it, since color is assigned to whole faces.

Leave small marks on a surface that keep the silhouette as it is, such as screws, panel seams, and vents, to surface detail, which paints them without triangles.
