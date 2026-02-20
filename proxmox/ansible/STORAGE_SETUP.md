# Ajouter un disque de stockage à Proxmox via Ansible

## Configuration

Les variables de configuration se trouvent dans `roles/configure/vars/main/storage.yml`:

```yaml
configure_storage_disk_device: /dev/sdb        # Disque à utiliser
configure_storage_name: hdd-storage            # Nom du storage dans Proxmox
configure_storage_mount_point: /mnt/pve/hdd-storage
configure_storage_filesystem_type: ext4        # ext4 ou xfs
configure_storage_type: dir                    # dir, lvm, lvmthin, zfspool
configure_storage_content: backup,iso,vztmpl   # Types de contenu autorisés
configure_storage_force_format: false          # ⚠️ true = efface toutes les données
```

## Types de contenu Proxmox

| Contenu | Description |
|---------|-------------|
| `images` | Disques de VMs (qcow2, raw) |
| `rootdir` | Conteneurs (CT) |
| `vztmpl` | Templates de conteneurs |
| `backup` | Sauvegardes (VMs/CT) |
| `iso` | Images ISO |
| `snippets` | Scripts cloud-init, hooks |

## Configurations recommandées

### 1. Stockage pour backups + ISO (931 GB disponible)
```yaml
configure_storage_name: hdd-backup
configure_storage_content: backup,iso,vztmpl
```

### 2. Stockage pour VMs
```yaml
configure_storage_name: hdd-vms
configure_storage_content: images,rootdir
```

### 3. Stockage mixte
```yaml
configure_storage_name: hdd-storage
configure_storage_content: backup,iso,vztmpl,images,rootdir
```

## Utilisation

### Exécuter uniquement le setup storage

```bash
ansible-playbook -i inventory.yml playbook.yml --tags setup_storage
```

### Exécuter tout le playbook (inclut storage)

```bash
ansible-playbook -i inventory.yml playbook.yml
```

### Premier formatage (⚠️ efface les données)

Modifier `storage.yml`:
```yaml
configure_storage_force_format: true
```

Puis exécuter:
```bash
ansible-playbook -i inventory.yml playbook.yml --tags setup_storage
```

**Important:** Remettre `configure_storage_force_format: false` après.

## Vérification

Après exécution, vérifier dans Proxmox:

```bash
# Lister les storages
pvesm status

# Voir les détails
pvesm list hdd-storage
```

Ou via l'interface web: **Datacenter > Storage**

## Troubleshooting

### Le disque existe déjà
Si le storage existe déjà, le playbook ne le recrée pas (idempotence).

### Changer la configuration
1. Supprimer le storage dans Proxmox: `pvesm remove hdd-storage`
2. Démonter: `umount /mnt/pve/hdd-storage`
3. Modifier `storage.yml`
4. Relancer le playbook

### Changer uniquement le type de contenu
```bash
pvesm set hdd-storage --content backup,iso,images
```
