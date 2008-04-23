import pkg_resources
import unittest
import traxio

def get_test_suite():
    modules = [traxio]
    suites = []
    for module in modules:
        suites.append(module.get_test_suite())
    suite = unittest.TestSuite( suites )
    return suite

def test():
    suite = get_test_suite()
    suite.debug()
    #unittest.TextTestRunner(verbosity=2).run(suite)

if __name__ == '__main__':
    test()
