import numpy as np
import logging
import umap
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt


def main():
    log_path = snakemake.log[0]
    logging.basicConfig(filename=log_path, level=logging.INFO,
                        format='%(asctime)s:%(filename)s:%(funcName)s:%(message)s')
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)

    table = np.loadtxt(snakemake.input.table, delimiter='\t')

    chosen_k = int(snakemake.params.chosen_k)
    chosen_mindist = float(snakemake.params.chosen_mindist)

    if chosen_k == 0:
        raise ValueError('No chosen number of neighbours - k - for umap')

    elif chosen_mindist == 0:
        raise ValueError('No chosen mindist for umap')

    uma = umap.UMAP(n_neighbors=chosen_k, min_dist=chosen_mindist, n_components=2, metric='euclidean',
                    random_state=15).fit_transform(table)
    plt.figure(figsize=(30, 20))
    plt.scatter(uma[:, 0], uma[:, 1])
    plt.title('UMAP with min_dist %s & n_neighbors %s' % (chosen_mindist, chosen_k))
    plt.savefig(snakemake.output.fig)

    np.savetxt(snakemake.output.umap_table, uma, delimiter='\t')


if __name__ == '__main__':
    main()
