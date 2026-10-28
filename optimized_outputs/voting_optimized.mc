contract Governance {
    state voting_open : bool;
    state eligible : bool;
    state has_voted : bool;
    state vote_count : int;

    function vote() {
        int voteWeight = 2;
        require((voting_open == true));
        require((eligible == true));
        require((has_voted == false));
        has_voted = true;
        vote_count = (vote_count + 1);
    }
}
