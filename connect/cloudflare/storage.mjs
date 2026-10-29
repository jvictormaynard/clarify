import { fail, GRANT_TTL } from './protocol.mjs';

export async function reserve(db, input, owner, hostname, hash, now, cap) {
  const results = await db.batch([
    db.prepare(`INSERT INTO computers
      (computer_id, owner_id, hpke_public_key, certificate_sha256, hostname, origin_port, state, created_at, updated_at)
      SELECT ?, ?, ?, ?, ?, ?, 'reserved', ?, ?
      WHERE NOT EXISTS (SELECT 1 FROM computers WHERE computer_id = ? OR hpke_public_key = ? OR hostname = ?)
        AND (SELECT count(*) FROM computers) < ?
        AND (SELECT count(*) FROM computers WHERE owner_id = ?) < 3`)
      .bind(input.computer_id, owner, input.hpke_public_key, input.certificate_sha256, hostname,
        input.origin_port, now, now, input.computer_id, input.hpke_public_key, hostname, cap, owner),
    db.prepare(`UPDATE computers SET grant_hash = ?, grant_expires_at = ?, origin_port = ?,
      certificate_sha256 = ?, updated_at = ? WHERE computer_id = ? AND owner_id = ?
      AND hpke_public_key = ? AND hostname = ? AND state IN ('reserved', 'ready') RETURNING computer_id`)
      .bind(hash, now + GRANT_TTL, input.origin_port, input.certificate_sha256, now,
        input.computer_id, owner, input.hpke_public_key, hostname),
  ]);
  if (results[1].results.length !== 1) fail(409, 'allocation_unavailable');
}

export async function consume(db, hash, operation, now) {
  const results = await db.batch([
    db.prepare('UPDATE control_lock SET operation_id = ?, acquired_at = ? WHERE id = 1 AND operation_id IS NULL')
      .bind(operation, now),
    db.prepare(`UPDATE computers SET state = 'claiming', operation_id = ?, grant_hash = NULL,
      grant_expires_at = NULL, failure_code = NULL, updated_at = ? WHERE grant_hash = ?
      AND grant_expires_at > ? AND state IN ('reserved', 'ready')
      AND EXISTS (SELECT 1 FROM control_lock WHERE id = 1 AND operation_id = ?) RETURNING *`)
      .bind(operation, now, hash, now, operation),
    db.prepare(`UPDATE control_lock SET operation_id = NULL, acquired_at = NULL WHERE operation_id = ?
      AND NOT EXISTS (SELECT 1 FROM computers WHERE operation_id = ? AND state = 'claiming')`)
      .bind(operation, operation),
  ]);
  if (results[1].results.length !== 1) fail(409, 'grant_unavailable');
  return results[1].results[0];
}

export async function checkpoint(db, computer, operation, column, value, now) {
  // Column names are internal constants; values always use bindings.
  if (!['tunnel_id', 'dns_id'].includes(column)) throw new Error('Invalid checkpoint');
  const result = await db.prepare(`UPDATE computers SET ${column} = ?, updated_at = ?
    WHERE computer_id = ? AND operation_id = ? AND state = 'claiming' RETURNING computer_id`)
    .bind(value, now, computer, operation).all();
  if (result.results.length !== 1) fail(502, 'allocation_unavailable');
}

export async function finish(db, computer, operation, now) {
  const result = await db.batch([
    db.prepare(`UPDATE computers SET state = 'ready', operation_id = NULL, updated_at = ?
      WHERE computer_id = ? AND operation_id = ? AND state = 'claiming' RETURNING computer_id`)
      .bind(now, computer, operation),
    db.prepare(`UPDATE control_lock SET operation_id = NULL, acquired_at = NULL WHERE operation_id = ?
      AND EXISTS (SELECT 1 FROM computers WHERE computer_id = ? AND state = 'ready' AND operation_id IS NULL)`)
      .bind(operation, computer),
  ]);
  if (result[0].results.length !== 1) fail(502, 'allocation_unavailable');
}

export async function stop(db, computer, operation, now, uncertain) {
  const statements = [db.prepare(`UPDATE computers SET state = ?, failure_code = ?, updated_at = ?
    WHERE computer_id = ? AND operation_id = ? AND state = 'claiming'`)
    .bind(uncertain ? 'uncertain' : 'blocked', uncertain ? 'provider_uncertain' : 'preflight_failed',
      now, computer, operation)];
  if (!uncertain) statements.push(db.prepare('UPDATE control_lock SET operation_id = NULL, acquired_at = NULL WHERE operation_id = ?').bind(operation));
  await db.batch(statements);
}
