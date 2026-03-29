Regenerate thumbnail should use the same buffering as the original open folder

Before the change you made to Copy SD : it would try to refresh right away every new image detected : when there were a lot of images, some seemed to be duplicated and thumbnail left empty

When new images detected in folder : it should follow the same rul as the original loading : that is the images shouold not be loaded right away but wait for there to be a sufficient number.