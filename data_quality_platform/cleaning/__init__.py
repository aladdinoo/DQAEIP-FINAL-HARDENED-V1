# Cleaning authorization gates - V1 foundation

class CleaningGate:
    """Authorization gate for cleaning operations.

    V1: All cleaning requires explicit authorization.
    Automatic cleaning is NOT enabled by default.
    """

    def __init__(self, auto_clean: bool = False):
        self.auto_clean = auto_clean

    def authorize(self, rule_id: str, row_count: int) -> bool:
        """Check if cleaning is authorized for this rule.

        V1: Only manual authorization (auto_clean must be True).
        """
        if not self.auto_clean:
            return False
        return True
