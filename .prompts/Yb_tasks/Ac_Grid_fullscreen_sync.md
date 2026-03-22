- grid / fullscreen : action in fullscreen also act on grid (selection, last for arrows or Esc, removed from filter / readd) so no change visible by the user
- fulscreen action act on 2 levels
- remove all the sync after close.
- Behaviour must be simple : action in fs => also action in grid (but lifecycle not the same so rollback in fullscreen eg labels not in filter => must be resolved correctly)

Currently it is an endless mess of synchronization issues with no end