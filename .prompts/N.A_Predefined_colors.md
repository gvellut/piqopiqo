Keep the function that does the generation as is
But add and use the following :
- add a constant that is a list of length 9  of colors : red blue greem yellow purple orange ... ditinct (neither white nor black though). in #abababa format. Try to distribute them at generation ie orange not next to yellow
- when Add label is done : depending on the new index : pick a color in the list. Unless that exact color is already in the list. Then choose the next. Loop around if needs be (since there are only 9 possible labels : it will eventually find something)
