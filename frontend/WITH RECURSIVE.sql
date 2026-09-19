WITH RECURSIVE
links(a, b) AS (
    SELECT e.from_node, e.to_node
    FROM edges e
    JOIN nodes n1 ON n1.node_id = e.from_node
    JOIN nodes n2 ON n2.node_id = e.to_node
    WHERE e.is_vertical = 0
      AND n1.floor_id = 'F6'
      AND n2.floor_id = 'F6'

    UNION

    SELECT e.to_node, e.from_node
    FROM edges e
    JOIN nodes n1 ON n1.node_id = e.from_node
    JOIN nodes n2 ON n2.node_id = e.to_node
    WHERE e.is_vertical = 0
      AND e.bidirectional = 1
      AND n1.floor_id = 'F6'
      AND n2.floor_id = 'F6'
),
reachable(node_id) AS (
    SELECT '626'

    UNION

    SELECT links.b
    FROM links
    JOIN reachable
      ON links.a = reachable.node_id
)
SELECT node_id
FROM reachable
WHERE node_id IN (
    'LIFT1-F6',
    'LIFT2-F6',
    'LIFT3-F6'
);