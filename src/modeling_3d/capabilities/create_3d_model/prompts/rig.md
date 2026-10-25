### Rigging

Rig the model so it is ready to move. Don't modify the shape unless asked. Rig it in model.py after the parts are built, so the script still builds the whole model from an empty scene, and a later change to a part keeps its rig.

Rig each kind of part this way:

- Parts that move on their own, such as a door, a lid, a wheel, or a drawer that slides out: make each its own named object, with its origin at its pivot and its motion declared as the check-3d-model skill describes.
- Parts that can be hidden, or swapped for another: make each its own named object too, and declare that as well. Build parts that swap for each other in the same place, so a swap only changes which one shows.
- What bends, such as a body or a tail: give it a skeleton, an armature with clearly named bones, with the mesh weighted to it at most four bones a vertex and enough geometry at each joint to bend cleanly. Build it in a neutral rest pose and export the skeleton in model.glb.
- Every other part: join them all into one object.
- Points other code will use, such as where another model attaches or where an effect starts: mark each with a named empty at that point.

A model with nothing that moves comes out with its parts joined into one object and its points marked.

Give each motion's axis in glTF's axes, in its parent's space. Blender exports the declaration as written, so Blender's +Z is glTF's +Y, and Blender's +Y is glTF's -Z.

Every object adds draw calls. If giving each moving part its own object would go over the draw call budget, stay within the budget instead: leave those parts in one mesh, move each with a bone of its own, weight every vertex fully to its part's bone, and declare each motion on its bone. Parts that are hidden or swapped stay their own objects even then, because a bone can't hide what it moves.

Pose the model the ways it moves and render those poses too, to check that it deforms and clears itself.
