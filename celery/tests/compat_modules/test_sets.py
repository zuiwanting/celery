from __future__ import absolute_import

import anyjson

from mock import Mock, patch

from celery.task import Task
from celery.task.sets import subtask, TaskSet
from celery.canvas import Signature

from celery.tests.case import AppCase


class MockTask(Task):
    name = 'tasks.add'

    def run(self, x, y, **kwargs):
        return x + y

    @classmethod
    def apply_async(cls, args, kwargs, **options):
        return (args, kwargs, options)

    @classmethod
    def apply(cls, args, kwargs, **options):
        return (args, kwargs, options)


class test_subtask(AppCase):

    def test_behaves_like_type(self):
        s = subtask('tasks.add', (2, 2), {'cache': True},
                    {'routing_key': 'CPU-bound'})
        self.assertDictEqual(subtask(s), s)

    def test_task_argument_can_be_task_cls(self):
        s = subtask(MockTask, (2, 2))
        self.assertEqual(s.task, MockTask.name)

    def test_apply_async(self):
        s = MockTask.subtask(
            (2, 2), {'cache': True}, {'routing_key': 'CPU-bound'},
        )
        args, kwargs, options = s.apply_async()
        self.assertTupleEqual(args, (2, 2))
        self.assertDictEqual(kwargs, {'cache': True})
        self.assertDictEqual(options, {'routing_key': 'CPU-bound'})

    def test_delay_argmerge(self):
        s = MockTask.subtask(
            (2, ), {'cache': True}, {'routing_key': 'CPU-bound'},
        )
        args, kwargs, options = s.delay(10, cache=False, other='foo')
        self.assertTupleEqual(args, (10, 2))
        self.assertDictEqual(kwargs, {'cache': False, 'other': 'foo'})
        self.assertDictEqual(options, {'routing_key': 'CPU-bound'})

    def test_apply_async_argmerge(self):
        s = MockTask.subtask(
            (2, ), {'cache': True}, {'routing_key': 'CPU-bound'},
        )
        args, kwargs, options = s.apply_async((10, ),
                                              {'cache': False, 'other': 'foo'},
                                              routing_key='IO-bound',
                                              exchange='fast')

        self.assertTupleEqual(args, (10, 2))
        self.assertDictEqual(kwargs, {'cache': False, 'other': 'foo'})
        self.assertDictEqual(options, {'routing_key': 'IO-bound',
                                       'exchange': 'fast'})

    def test_apply_argmerge(self):
        s = MockTask.subtask(
            (2, ), {'cache': True}, {'routing_key': 'CPU-bound'},
        )
        args, kwargs, options = s.apply((10, ),
                                        {'cache': False, 'other': 'foo'},
                                        routing_key='IO-bound',
                                        exchange='fast')

        self.assertTupleEqual(args, (10, 2))
        self.assertDictEqual(kwargs, {'cache': False, 'other': 'foo'})
        self.assertDictEqual(
            options, {'routing_key': 'IO-bound', 'exchange': 'fast'},
        )

    def test_is_JSON_serializable(self):
        s = MockTask.subtask(
            (2, ), {'cache': True}, {'routing_key': 'CPU-bound'},
        )
        s.args = list(s.args)                   # tuples are not preserved
                                                # but this doesn't matter.
        self.assertEqual(s, subtask(anyjson.loads(anyjson.dumps(s))))

    def test_repr(self):
        s = MockTask.subtask((2, ), {'cache': True})
        self.assertIn('2', repr(s))
        self.assertIn('cache=True', repr(s))

    def test_reduce(self):
        s = MockTask.subtask((2, ), {'cache': True})
        cls, args = s.__reduce__()
        self.assertDictEqual(dict(cls(*args)), dict(s))


class test_TaskSet(AppCase):

    def test_task_arg_can_be_iterable__compat(self):
        ts = TaskSet([MockTask.subtask((i, i))
                      for i in (2, 4, 8)], app=self.app)
        self.assertEqual(len(ts), 3)

    def test_respects_ALWAYS_EAGER(self):
        app = self.app

        class MockTaskSet(TaskSet):
            applied = 0

            def apply(self, *args, **kwargs):
                self.applied += 1

        ts = MockTaskSet(
            [MockTask.subtask((i, i)) for i in (2, 4, 8)],
            app=self.app,
        )
        app.conf.CELERY_ALWAYS_EAGER = True
        try:
            ts.apply_async()
        finally:
            app.conf.CELERY_ALWAYS_EAGER = False
        self.assertEqual(ts.applied, 1)

        with patch('celery.task.sets.get_current_worker_task') as gwt:
            parent = gwt.return_value = Mock()
            ts.apply_async()
            self.assertTrue(parent.add_trail.called)

    def test_apply_async(self):
        applied = [0]

        class mocksubtask(Signature):

            def apply_async(self, *args, **kwargs):
                applied[0] += 1

        ts = TaskSet([mocksubtask(MockTask, (i, i))
                      for i in (2, 4, 8)], app=self.app)
        ts.apply_async()
        self.assertEqual(applied[0], 3)

        class Publisher(object):

            def send(self, *args, **kwargs):
                pass

        ts.apply_async(publisher=Publisher())

        # setting current_task

        @self.app.task
        def xyz():
            pass

        from celery._state import _task_stack
        xyz.push_request()
        _task_stack.push(xyz)
        try:
            ts.apply_async(publisher=Publisher())
        finally:
            _task_stack.pop()
            xyz.pop_request()

    def test_apply(self):

        applied = [0]

        class mocksubtask(Signature):

            def apply(self, *args, **kwargs):
                applied[0] += 1

        ts = TaskSet([mocksubtask(MockTask, (i, i))
                      for i in (2, 4, 8)], app=self.app)
        ts.apply()
        self.assertEqual(applied[0], 3)

    def test_set_app(self):
        ts = TaskSet([], app=self.app)
        ts.app = 42
        self.assertEqual(ts.app, 42)

    def test_set_tasks(self):
        ts = TaskSet([], app=self.app)
        ts.tasks = [1, 2, 3]
        self.assertEqual(ts, [1, 2, 3])

    def test_set_Publisher(self):
        ts = TaskSet([], app=self.app)
        ts.Publisher = 42
        self.assertEqual(ts.Publisher, 42)
