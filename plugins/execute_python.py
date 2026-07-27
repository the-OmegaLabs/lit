import contextlib
import io


class Plugin:
    def __init__(self):
        self.name = "Execute python script"
        self.version = 'v1.0'
        self.author = 'Stevesuk0 <stevesukawa@outlook.com>'

        self.export_function = {
            'Execute python': self.execute_python_code
        }

    def execute_python_code(self, code: str):
        """
        Execute Python code and return the output.
        
        Note:
        This is similar to exec(), but captures stdout and errors.
        Do not use directly in production without sandboxing.
        """
        stdout = io.StringIO()
        stderr = io.StringIO()

        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exec(code, {})

            return {
                "status": "success",
                "output": stdout.getvalue(),
                "error": stderr.getvalue()
            }

        except Exception as e:
            return {
                "status": "error",
                "output": stdout.getvalue(),
                "error": str(e)
            }