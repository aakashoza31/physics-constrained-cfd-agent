"""Uniform startup consistent with the canonical tutorial, not forced shock data."""
def initial_state(spec):
    return {'p':spec.pressure,'T':spec.temperature,'U':(spec.velocity,0.0,0.0)}
