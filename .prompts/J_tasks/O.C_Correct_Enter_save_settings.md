is 

   if is_enter and is_self_or_child:
            if hasattr(self, "_save_btn") and self._save_btn.hasFocus():
                if self._save_btn.isEnabled():
                    self._on_save()
                event.accept()
                return True

necessary ?

It would seem : if the button has focuse, then it should be standard for an enter to activate it ?