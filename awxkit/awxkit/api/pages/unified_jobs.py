from pprint import pformat

import yaml.parser
import yaml.scanner
import yaml

from awxkit.utils import args_string_to_list, seconds_since_date_string
from awxkit.api.resources import resources
from awxkit.api.mixins import HasStatus
import awxkit.exceptions as exc
from . import base
from . import page


class UnifiedJob(HasStatus, base.Base):
    """Base class for unified job pages (e.g. project_updates, inventory_updates
    and jobs).
    """

    def __str__(self):
        # NOTE: I use .replace('%', '%%') to workaround an odd string
        # formatting issue where result_stdout contained '%s'.  This later caused
        # a python traceback when attempting to display output from this method.
        items = ['id', 'name', 'status', 'failed', 'result_stdout', 'result_traceback',
                 'job_explanation', 'job_args']
        info = []
        for item in [x for x in items if hasattr(self, x)]:
            info.append('{0}:{1}'.format(item, getattr(self, item)))
        output = '<{0.__class__.__name__} {1}>'.format(self, ', '.join(info))
        return output.replace('%', '%%')

    @property
    def result_stdout(self):
        if 'result_stdout' not in self.json and 'stdout' in self.related:
            return self.connection.get(
                self.related.stdout, query_parameters=dict(format='txt_download')
            ).content.decode()
        if str(self.json.get('result_stdout')) == 'stdout capture is missing' and 'stdout' in self.related:
            ping = self.walk(resources.ping)
            if self.execution_node != ping.active_node:
                self.connection.get(self.related.stdout, query_parameters=dict(format='txt_download'))
                self.get()
        return self.json.result_stdout.decode()

    def assert_text_in_stdout(self, expected_text, replace_spaces=None, replace_newlines=' '):
        """Assert text is found in stdout, and if not raise exception with entire stdout.

        Default behavior is to replace newline characters with a space, but this can be modified, including replacement
        with ''. Pass replace_newlines=None to disable.

        Additionally, you may replace any ' ' with another character (including ''). This is applied after the newline
        replacement. Default behavior is to not replace spaces.
        """
        stdout = self.result_stdout
        if replace_newlines is not None:
            stdout = stdout.replace('\n', replace_newlines)
        if replace_spaces is not None:
            stdout = stdout.replace(' ', replace_spaces)
        if expected_text not in stdout:
            pretty_stdout = pformat(stdout)
            raise AssertionError(
                'Expected "{}", but it was not found in stdout. Full stdout:\n {}'.format(expected_text, pretty_stdout)
            )

    @property
    def is_successful(self):
        """Return whether the current has completed successfully.

        This means that:
         * self.status == 'successful'
         * self.has_traceback == False
         * self.failed == False
        """
        return super(UnifiedJob, self).is_successful and not (self.has_traceback or self.failed)

    def wait_until_status(self, status, interval=1, timeout=60, since_job_created=True, **kwargs):
        if since_job_created:
            timeout = timeout - seconds_since_date_string(self.created)
        return super(UnifiedJob, self).wait_until_status(status, interval, timeout, **kwargs)

    def wait_until_completed(self, interval=5, timeout=60 * 8, since_job_created=True, **kwargs):
        if since_job_created:
            timeout = timeout - seconds_since_date_string(self.created)
        return super(UnifiedJob, self).wait_until_completed(interval, timeout, **kwargs)

    @property
    def has_traceback(self):
        """Return whether a traceback has been detected in result_traceback"""
        try:
            tb = str(self.result_traceback)
        except AttributeError:
            # If record obtained from list view, then traceback isn't given
            # and result_stdout is only given for some types
            # we must suppress AttributeError or else it will be mis-interpreted
            # by __getattr__
            tb = ''
        return 'Traceback' in tb

    def cancel(self):
        cancel = self.get_related('cancel')
        if not cancel.can_cancel:
            return
        try:
            cancel.post()
        except exc.MethodNotAllowed as e:
            # Race condition where job finishes between can_cancel
            # check and post.
            if not any("not allowed" in field for field in e.msg.values()):
                raise(e)
        return self.get()

    @property
    def job_args(self):
        """Helper property to return flattened cmdline arg tokens in a list.
        Flattens arg strings for rough inclusion checks:
        ```assert "thing" in unified_job.job_args```
        ```assert dict(extra_var=extra_var_val) in unified_job.job_args```
        If you need to ensure the job_args are of awx-provided format use raw unified_job.json.job_args.
        """
        def attempt_yaml_load(arg):
            try:
                return yaml.load(arg, Loader=yaml.FullLoader)
            except (yaml.parser.ParserError, yaml.scanner.ScannerError):
                return str(arg)

        args = []
        if not self.json.job_args:
            return ""
        for arg in yaml.load(self.json.job_args, Loader=yaml.FullLoader):
            try:
                args.append(yaml.load(arg, Loader=yaml.FullLoader))
            except (yaml.parser.ParserError, yaml.scanner.ScannerError):
                if arg[0] == '@':  # extra var file reference
                    args.append(attempt_yaml_load(arg))
                elif args[-1] == '-c':  # this arg is likely sh arg string
                    args.extend([attempt_yaml_load(item) for item in args_string_to_list(arg)])
                else:
                    raise
        return args


class UnifiedJobs(page.PageList, UnifiedJob):

    pass


page.register_page([resources.unified_jobs,
                    resources.instance_related_jobs,
                    resources.instance_group_related_jobs,
                    resources.schedules_jobs], UnifiedJobs)