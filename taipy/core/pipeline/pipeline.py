from __future__ import annotations

import uuid
from typing import Any, Callable, Dict, List, Optional, Set

import networkx as nx

from taipy.core.common._entity import _Entity
from taipy.core.common._properties import _Properties
from taipy.core.common._reload import reload, self_reload, self_setter
from taipy.core.common._utils import _fcts_to_dict
from taipy.core.common._validate_id import _validate_id
from taipy.core.common.alias import PipelineId
from taipy.core.data.data_node import DataNode
from taipy.core.job.job import Job
from taipy.core.pipeline.pipeline_model import PipelineModel
from taipy.core.task.task import Task


class Pipeline(_Entity):
    """
    A Pipeline entity that holds a list of tasks and additional arguments representing a set of data processing elements
    connected in series.

    Attributes:
        config_id (str): Identifier of the pipeline configuration. Must be a valid Python variable name.
        properties (dict):  List of additional arguments.
        tasks (List[Task]): List of tasks.
        pipeline_id (str): Unique identifier of this pipeline.
        parent_id (str):  Identifier of the parent (pipeline_id, scenario_id, cycle_id) or `None`.
    """

    ID_PREFIX = "PIPELINE"
    __SEPARATOR = "_"
    MANAGER_NAME = "pipeline"

    def __init__(
        self,
        config_id: str,
        properties: Dict[str, Any],
        tasks: List[Task],
        pipeline_id: PipelineId = None,
        parent_id: Optional[str] = None,
        subscribers: Set[Callable] = None,
    ):
        self._config_id = _validate_id(config_id)
        self._tasks = {task.config_id: task for task in tasks}
        self.id: PipelineId = pipeline_id or self.new_id(self._config_id)
        self._parent_id = parent_id
        self.is_consistent = self.__is_consistent()

        self._subscribers = subscribers or set()
        self._properties = _Properties(self, **properties)

    def __getstate__(self):
        return self.id

    def __setstate__(self, id):
        from taipy.core.pipeline.pipeline_manager import PipelineManager

        p = PipelineManager._get(id)
        self.__dict__ = p.__dict__

    @property  # type: ignore
    @self_reload(MANAGER_NAME)
    def config_id(self):
        return self._config_id

    @config_id.setter  # type: ignore
    @self_setter(MANAGER_NAME)
    def config_id(self, val):
        self._config_id = val

    @property  # type: ignore
    @self_reload(MANAGER_NAME)
    def tasks(self):
        return self._tasks

    @tasks.setter  # type: ignore
    @self_setter(MANAGER_NAME)
    def tasks(self, val):
        self._tasks = {task.config_id: task for task in val}

    @property  # type: ignore
    @self_reload(MANAGER_NAME)
    def parent_id(self):
        return self._parent_id

    @parent_id.setter  # type: ignore
    @self_setter(MANAGER_NAME)
    def parent_id(self, val):
        self._parent_id = val

    @property  # type: ignore
    @self_reload(MANAGER_NAME)
    def subscribers(self):
        return self._subscribers

    @subscribers.setter  # type: ignore
    @self_setter(MANAGER_NAME)
    def subscribers(self, val):
        self._subscribers = val or set()

    @property  # type: ignore
    def properties(self):
        self._properties = reload("pipeline", self)._properties
        return self._properties

    def __eq__(self, other):
        return self.id == other.id

    @staticmethod
    def new_id(config_id: str) -> PipelineId:
        return PipelineId(Pipeline.__SEPARATOR.join([Pipeline.ID_PREFIX, _validate_id(config_id), str(uuid.uuid4())]))

    def __getattr__(self, attribute_name):
        protected_attribute_name = _validate_id(attribute_name)
        if protected_attribute_name in self.properties:
            return self.properties[protected_attribute_name]
        if protected_attribute_name in self._tasks:
            return self._tasks[protected_attribute_name]
        for task in self._tasks.values():
            if protected_attribute_name in task.input:
                return task.input[protected_attribute_name]
            if protected_attribute_name in task.output:
                return task.output[protected_attribute_name]
        raise AttributeError(f"{attribute_name} is not an attribute of pipeline {self.id}")

    def __is_consistent(self) -> bool:
        dag = self.__build_dag()
        if not nx.is_directed_acyclic_graph(dag):
            return False
        is_data_node = True
        for nodes in nx.topological_generations(dag):
            for node in nodes:
                if is_data_node and not isinstance(node, DataNode):
                    return False
                if not is_data_node and not isinstance(node, Task):
                    return False
            is_data_node = not is_data_node
        return True

    def __build_dag(self):
        graph = nx.DiGraph()
        for task in self._tasks.values():
            if has_input := task.input:
                for predecessor in task.input.values():
                    graph.add_edges_from([(predecessor, task)])
            if has_output := task.output:
                for successor in task.output.values():
                    graph.add_edges_from([(task, successor)])
            if not has_input and not has_output:
                graph.add_node(task)
        return graph

    def add_subscriber(self, callback: Callable):
        self._subscribers = reload("pipeline", self)._subscribers
        self._subscribers.add(callback)

    def remove_subscriber(self, callback: Callable):
        self._subscribers = reload("pipeline", self)._subscribers
        self._subscribers.remove(callback)

    def to_model(self) -> PipelineModel:
        return PipelineModel(
            self.id,
            self.parent_id,
            self._config_id,
            self._properties.data,
            [task.id for task in self._tasks.values()],
            _fcts_to_dict(list(self._subscribers)),
        )

    def get_sorted_tasks(self) -> List[List[Task]]:
        dag = self.__build_dag()
        return list(nodes for nodes in nx.topological_generations(dag) if (Task in (type(node) for node in nodes)))

    def subscribe(self, callback: Callable[[Pipeline, Job], None]):
        from taipy.core.pipeline.pipeline_manager import PipelineManager

        return PipelineManager.subscribe(callback, self)

    def unsubscribe(self, callback: Callable[[Pipeline, Job], None]):
        from taipy.core.pipeline.pipeline_manager import PipelineManager

        return PipelineManager.unsubscribe(callback, self)

    def submit(self, callbacks: Optional[List[Callable]] = None, force: bool = False):
        from taipy.core.pipeline.pipeline_manager import PipelineManager

        return PipelineManager.submit(self, callbacks, force)
