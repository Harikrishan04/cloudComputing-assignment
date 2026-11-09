# Subnet Allocation — 10.20.0.0/16

Allocated largest-requirement-first, starting at 10.20.0.0, each subnet placed right
after the previous one, using the smallest block (largest prefix) that satisfies
`usable hosts = 2^(32-prefix) - 2 >= required hosts`.

| Subnet | Hosts needed | Network | Prefix | Usable host range | Broadcast | Usable hosts |
|---|---|---|---|---|---|---|
| app | 1,000 | 10.20.0.0/22 | /22 | 10.20.0.1 – 10.20.3.254 | 10.20.3.255 | 1022 |
| public | 250 | 10.20.4.0/24 | /24 | 10.20.4.1 – 10.20.4.254 | 10.20.4.255 | 254 |
| data | 100 | 10.20.5.0/25 | /25 | 10.20.5.1 – 10.20.5.126 | 10.20.5.127 | 126 |
| management | 20 | 10.20.5.128/27 | /27 | 10.20.5.129 – 10.20.5.158 | 10.20.5.159 | 30 |

## Working

- **app** needs 1,000 usable hosts. /22 gives 2^10-2 = 1022 ≥ 1000 (the next smaller
  block, /23, gives only 510, which is not enough). Block: 10.20.0.0/22
  (10.20.0.0 – 10.20.3.255), 1024 addresses.
- **public** starts right after app, at 10.20.4.0. Needs 250 usable hosts. /24 gives
  254 ≥ 250 (/25 gives only 126, not enough). Block: 10.20.4.0/24, 256 addresses.
- **data** starts at 10.20.5.0. Needs 100 usable hosts. /25 gives 126 ≥ 100 (/26 gives
  only 62, not enough). Block: 10.20.5.0/25, 128 addresses.
- **management** starts right after data, at 10.20.5.128. Needs 20 usable hosts. /27
  gives 30 ≥ 20 (/28 gives only 14, not enough). Block: 10.20.5.128/27, 32 addresses.

All four blocks are contiguous and non-overlapping, and all stay inside 10.20.0.0/16.

## NACL rule-order explanation

A NACL is **stateless**: it does not remember that a packet belongs to an existing
connection, so a reply packet (e.g. the server's response on port 443 going back to a
client's ephemeral port) is just another packet evaluated independently. Without an
explicit "allow the replies" rule in each direction, a stateless NACL would allow the
request out but then silently drop the reply coming back, breaking every connection.
That is why the inbound list has a rule allowing TCP 1024-65535 from the app subnet
(replies from the backend), and the outbound list allows TCP 1024-65535 to anywhere
(replies going back to clients).

Rule order matters because the simulator (and real NACLs) use **first match wins**,
evaluated from the lowest rule number up. The deny rule for 198.51.100.0/24 is given
rule number 10, lower than the allow-TCP-80/443-from-anywhere rules (100, 110). If the
deny rule had a higher number than the "allow from anywhere" rules, those broader
allow rules would match first for any packet from 198.51.100.0/24 on port 80/443, and
the deny rule would never be reached — the abusive range would never actually be
blocked on the web ports, defeating its purpose.
