# osh1 does a clone of a pipeline, being careful to replace functions by references before the copy, and then fix up
# the copy afterward. Is this really necessary?

import io
import pickle


class AbstractOp:

    def __init__(self):
        self.base = 111


class Op(AbstractOp):

    def __init__(self, name, f):
        super().__init__()
        self.name = name
        self.f = f
        self.next = None

    def __repr__(self):
        return 'Op(#{}, {}, {})'.format(hash(self), self.name, self.base)

    def __getstate__(self):
        return self.__dict__

    def __setstate__(self, state):
        self.__dict__.update(state)

    def connect(self, next):
        self.next = next

    def run(self):
        return self.f(self)


def f(op):
    return 'In f({})'.format(op.name)


def g(op):
    return 'In g({})'.format(op.name)


def traverse(label, op):
    print(label)
    while op:
        print('    {}: {}'.format(op, op.run()))
        op = op.next


def clone(x):
    buffer = io.BytesIO()
    pickler = pickle.Pickler(buffer)
    pickler.dump(x)
    buffer.seek(0)
    unpickler = pickle.Unpickler(buffer)
    return unpickler.load()


a = Op('a', f)
b = Op('b', g)
a.connect(b)
traverse('original', a)

acopy = clone(a)
traverse('copy', acopy)