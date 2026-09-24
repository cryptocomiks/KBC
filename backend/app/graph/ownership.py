"""Ownership-structure analytics on the resolved network (networkx)."""

from __future__ import annotations

from collections.abc import Iterable

import networkx as nx

from app.models import Entity, EntityType, Relationship, RelationType

MAX_PATH_LENGTH = 8
MAX_CYCLES = 50


def ownership_graph(relationships: Iterable[Relationship]) -> nx.DiGraph:
    """Directed graph owner -> owned company, weighted by share percentage."""
    g = nx.DiGraph()
    for rel in relationships:
        if rel.type == RelationType.SHAREHOLDER and rel.is_active:
            g.add_edge(rel.source_id, rel.target_id, pct=rel.share_pct)
    return g


def find_cycles(g: nx.DiGraph) -> list[list[str]]:
    cycles = []
    for cycle in nx.simple_cycles(g):
        cycles.append(cycle)
        if len(cycles) >= MAX_CYCLES:
            break
    return cycles


def corporate_layers_above(
    g: nx.DiGraph, company_id: str, entities: dict[str, Entity]
) -> list[str]:
    """Longest chain of *corporate* owners above a company (cycle-safe DFS)."""
    best: list[str] = []

    def dfs(node: str, path: list[str]) -> None:
        nonlocal best
        extended = False
        for owner in g.predecessors(node):
            ent = entities.get(owner)
            if owner in path or ent is None or ent.type != EntityType.COMPANY:
                continue
            if len(path) < MAX_PATH_LENGTH:
                extended = True
                dfs(owner, [*path, owner])
        if not extended and len(path) - 1 > len(best):
            best = path[1:]

    if company_id in g:
        dfs(company_id, [company_id])
    return best


def indirect_stakes(g: nx.DiGraph, owner_id: str) -> dict[str, float]:
    """Economic interest of `owner_id` in every company it reaches.

    Sum over simple paths of the product of percentages. Cycles are cut
    (simple paths only), which is the usual conservative approximation.
    Edges with an unknown percentage make the path unknown and are skipped.
    """
    stakes: dict[str, float] = {}
    if owner_id not in g:
        return stakes

    def walk(node: str, pct: float, visited: set[str]) -> None:
        for owned in g.successors(node):
            if owned in visited:
                continue
            edge_pct = g.edges[node, owned].get("pct")
            if edge_pct is None:
                continue
            share = pct * edge_pct / 100
            stakes[owned] = stakes.get(owned, 0.0) + share
            if len(visited) < MAX_PATH_LENGTH:
                walk(owned, share, visited | {owned})

    walk(owner_id, 100.0, {owner_id})
    return {k: round(v, 2) for k, v in stakes.items()}
