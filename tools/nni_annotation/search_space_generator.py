# Copyright (c) Microsoft Corporation. All rights reserved.
#
# MIT License
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
# associated documentation files (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge, publish, distribute,
# sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or
# substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED *AS IS*, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT
# NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
# DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT
# OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
# ==================================================================================================


import ast
import astor
import numbers

# pylint: disable=unidiomatic-typecheck


# list of functions related to search space generating
_ss_funcs = [
    'choice',
    'randint',
    'uniform',
    'quniform',
    'loguniform',
    'qloguniform',
    'normal',
    'qnormal',
    'lognormal',
    'qlognormal',
    'function_choice',
    'mutable_layer'
]


class SearchSpaceGenerator(ast.NodeTransformer):
    """Generate search space from smart parater APIs"""

    def __init__(self, module_name):
        self.module_name = module_name
        self.search_space = {}
        self.last_line = 0  # last parsed line, useful for error reporting

    def generate_mutable_layer_search_space(self, args):
        mutable_block = args[0].s
        mutable_layer = args[1].s
        if mutable_block not in self.search_space:
            self.search_space[mutable_block] = dict()
        self.search_space[mutable_block][mutable_layer] = {
            'layer_choice': [key.s for key in args[2].keys],
            'optional_inputs': [key.s for key in args[5].keys],
            'optional_input_size': args[6].n
        }


    def visit_Call(self, node):  # pylint: disable=invalid-name
        self.generic_visit(node)

        # ignore if the function is not 'nni.*'
        if type(node.func) is not ast.Attribute:
            return node
        if type(node.func.value) is not ast.Name:
            return node
        if node.func.value.id != 'nni':
            return node

        # ignore if its not a search space function (e.g. `report_final_result`)
        func = node.func.attr
        if func not in _ss_funcs:
            return node

        self.last_line = node.lineno

        if func == 'mutable_layer':
            self.generate_mutable_layer_search_space(node.args)
            return node

        if node.keywords:
            # there is a `name` argument
            assert len(node.keywords) == 1, 'Smart parameter has keyword argument other than "name"'
            assert node.keywords[0].arg == 'name', 'Smart paramater\'s keyword argument is not "name"'
            assert type(node.keywords[0].value) is ast.Str, 'Smart parameter\'s name must be string literal'
            name = node.keywords[0].value.s
            specified_name = True
        else:
            # generate the missing name automatically
            name = '__line' + str(str(node.args[-1].lineno))
            specified_name = False
            node.keywords = list()

        if func in ('choice', 'function_choice'):
            # we will use keys in the dict as the choices, which is generated by code_generator according to the args given by user
            assert len(node.args) == 1, 'Smart parameter has arguments other than dict'
            # check if it is a number or a string and get its value accordingly
            args = [key.n if type(key) is ast.Num else key.s for key in node.args[0].keys]
        else:
            # arguments of other functions must be literal number
            assert all(isinstance(ast.literal_eval(astor.to_source(arg)), numbers.Real) for arg in node.args), \
            'Smart parameter\'s arguments must be number literals'
            args = [ast.literal_eval(astor.to_source(arg)) for arg in node.args]

        key = self.module_name + '/' + name + '/' + func
        # store key in ast.Call
        node.keywords.append(ast.keyword(arg='key', value=ast.Str(s=key)))

        if func == 'function_choice':
            func = 'choice'
        value = {'_type': func, '_value': args}

        if specified_name:
            # multiple functions with same name must have identical arguments
            old = self.search_space.get(key)
            assert old is None or old == value, 'Different smart parameters have same name'
        else:
            # generated name must not duplicate
            assert key not in self.search_space, 'Only one smart parameter is allowed in a line'

        self.search_space[key] = value

        return node


def generate(module_name, code):
    """Generate search space.
    Return a serializable search space object.
    module_name: name of the module (str)
    code: user code (str)
    """
    try:
        ast_tree = ast.parse(code)
    except Exception:
        raise RuntimeError('Bad Python code')

    visitor = SearchSpaceGenerator(module_name)
    try:
        visitor.visit(ast_tree)
    except AssertionError as exc:
        raise RuntimeError('%d: %s' % (visitor.last_line, exc.args[0]))
    return visitor.search_space, astor.to_source(ast_tree)
