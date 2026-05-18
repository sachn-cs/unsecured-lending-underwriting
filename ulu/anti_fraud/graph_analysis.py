"""Coalition detection and graph anomaly analysis."""

from __future__ import annotations

from collections import defaultdict


class GraphAnomalyDetector:
    """Detects sponsor rings, wash lending, and Sybil clusters."""

    def __init__(self) -> None:
        pass

    def detect_cycles(self, edges: list[tuple[str, str]]) -> list[list[str]]:
        """Returns all cycles in the delegation graph (should be empty in valid forest)."""
        adjacency: dict[str, list[str]] = defaultdict(list)
        for parent, child in edges:
            adjacency[parent].append(child)

        cycles: list[list[str]] = []
        visited: set[str] = set()
        stack: set[str] = set()
        path: list[str] = []

        def dfs(node: str) -> None:
            visited.add(node)
            stack.add(node)
            path.append(node)
            for neighbor in adjacency[node]:
                if neighbor not in visited:
                    dfs(neighbor)
                elif neighbor in stack:
                    cycle_start = path.index(neighbor)
                    cycles.append(path[cycle_start:] + [neighbor])
            path.pop()
            stack.remove(node)

        for node in list(adjacency.keys()):
            if node not in visited:
                dfs(node)
        return cycles

    def detect_wash_lending(self, transactions: list[dict[str, str | float]], window_hours: float = 24.0) -> list[dict]:
        """Flags borrowers who repay and immediately re-borrow."""
        from datetime import datetime, timedelta

        flagged: list[dict] = []
        borrower_events: dict[str, list[dict]] = defaultdict(list)
        for tx in transactions:
            borrower_events[str(tx["borrower_id"])].append(tx)

        for borrower_id, events in borrower_events.items():
            events.sort(key=lambda e: datetime.fromisoformat(str(e["timestamp"])))
            for i in range(len(events)):
                if events[i]["type"] != "repayment":
                    continue
                for j in range(i + 1, len(events)):
                    if events[j]["type"] != "origination":
                        continue
                    repay_time = datetime.fromisoformat(str(events[i]["timestamp"]))
                    orig_time = datetime.fromisoformat(str(events[j]["timestamp"]))
                    if (orig_time - repay_time) <= timedelta(hours=window_hours):
                        flagged.append(
                            {
                                "borrower_id": borrower_id,
                                "repayment_time": repay_time.isoformat(),
                                "reborrow_time": orig_time.isoformat(),
                            }
                        )
                        break
        return flagged

    def detect_sybil_clusters(
        self, edges: list[tuple[str, str]], threshold: int = 3, density_threshold: float = 0.5
    ) -> list[list[str]]:
        """Finds tightly connected components that may indicate synthetic identities.

        Uses graph density (2*E / (V*(V-1))) instead of raw component size to
        avoid false positives on legitimate delegation trees.
        """
        adjacency: dict[str, set[str]] = defaultdict(set)
        for parent, child in edges:
            adjacency[parent].add(child)
            adjacency[child].add(parent)

        visited: set[str] = set()
        clusters: list[list[str]] = []

        def bfs(start: str) -> list[str]:
            queue = [start]
            component: set[str] = {start}
            while queue:
                node = queue.pop(0)
                for neighbor in adjacency[node]:
                    if neighbor not in component:
                        component.add(neighbor)
                        queue.append(neighbor)
            return list(component)

        for node in list(adjacency.keys()):
            if node not in visited:
                component = bfs(node)
                visited.update(component)
                v = len(component)
                if v >= threshold:
                    e = sum(len(adjacency[n]) for n in component) // 2
                    density = (2 * e) / (v * (v - 1)) if v > 1 else 0.0
                    if density >= density_threshold:
                        clusters.append(component)
        return clusters
