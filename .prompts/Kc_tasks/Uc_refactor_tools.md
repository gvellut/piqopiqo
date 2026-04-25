Refactor tools : flickr upload, copy sd, archive, apply gpx / clear gps, set Lens info, save Exif

Define a framework for such tools :
- it manages the dialog window, 
- it manages possibly the background tasks (using QThreadPool) if requested by the tool
- it manages the transition of screens
- it manages the sizing
- it centralizes the events and dispatch (event bus) : no event spaghetti like in main_window (keep that class as is for now)
- keep the number of concepts limited and share it with the tools (and further similar tools that may exist in the future) : do not duplicate "similar but not quite" concepts like now with the different tools where there are slight differences for the same situation for seemingly no good reasons
- it manages the progress bar + progress counts (xx / <total>) label, if requested by the tool

For each tool : 
- refactor to make use of the framework
- make it obvious the ordering of screens and response to events : the screens and transitions should be managed in a structure for each tool (with responses and screen defitions) not scattered around. It should include screen size (or dynamic sizeing ie size depends on visible items)
- each tool should become relatively simple with most code in it business logic, not plumbing

