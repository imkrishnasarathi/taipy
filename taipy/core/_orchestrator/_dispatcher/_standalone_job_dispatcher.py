# Copyright 2021-2024 Avaiga Private Limited
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on
# an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

from concurrent.futures import Executor, ProcessPoolExecutor
from functools import partial
from typing import Any, Callable, Dict, Optional

from taipy.config._serializer._toml_serializer import _TomlSerializer
from taipy.config.config import Config

from ...job.job import Job
from .._abstract_orchestrator import _AbstractOrchestrator
from ._job_dispatcher import _JobDispatcher
from ._task_function_wrapper import _TaskFunctionWrapper


class _StandaloneJobDispatcher(_JobDispatcher):
    """Manages job dispatching (instances of `Job^` class) in an asynchronous way using a ProcessPoolExecutor."""

    def __init__(self, orchestrator: _AbstractOrchestrator, subproc_initializer: Optional[Callable] = None):
        super().__init__(orchestrator)
        max_workers = Config.job_config.max_nb_of_workers or 1
        self._executor: Executor = ProcessPoolExecutor(
            max_workers=max_workers,
            initializer=subproc_initializer,
        )  # type: ignore
        self._dispatched_processes: Dict[str, Any] = {}
        self._nb_available_workers = self._executor._max_workers  # type: ignore

    def _can_execute(self) -> bool:
        """Returns True if the dispatcher have resources to dispatch a job."""
        return self._nb_available_workers > 0

    def run(self):
        with self._executor:
            super().run()
        self._logger.debug("Standalone job dispatcher: Pool executor shut down")

    def _dispatch(self, job: Job):
        """Dispatches the given `Job^` on an available worker for execution.

        Parameters:
            job (Job^): The job to submit on an executor with an available worker.
        """

        self._nb_available_workers -= 1
        config_as_string = _TomlSerializer()._serialize(Config._applied_config)  # type: ignore[attr-defined]
        future = self._executor.submit(_TaskFunctionWrapper(job.id, job.task), config_as_string=config_as_string)

        self._set_dispatched_processes(job.id, future)  # type: ignore
        future.add_done_callback(self._release_worker)  # We must release the worker before updating the job status
        # so that the worker is available for another job as soon as possible.
        future.add_done_callback(partial(self._update_job_status_from_future, job))

    def _set_dispatched_processes(self, job_id, process):
        self._dispatched_processes[job_id] = process

    def _release_worker(self, _):
        self._nb_available_workers += 1

    def _update_job_status_from_future(self, job: Job, ft):
        self._pop_dispatched_process(job.id)  # type: ignore
        self._update_job_status(job, ft.result())

    def _pop_dispatched_process(self, job_id: str, default=None):
        return self._dispatched_processes.pop(job_id, default)

    def _is_dispatched(self, job_id: str) -> bool:
        return job_id in self._dispatched_processes.keys()

    def _remove_dispatched_job(self, job_id: str):
        self._pop_dispatched_process(job_id)
